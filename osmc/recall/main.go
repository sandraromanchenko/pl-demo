// Command recall probes a golden query set against the live vector index and
// exports the mean as the Prometheus gauge vector_search_recall_at_10.
// Truth is an exact scan of the live documents unless RECALL_TRUTH=frozen.
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"time"

	"pl-demo/osmc/internal/golden"
	"pl-demo/osmc/internal/recallmath"
	"pl-demo/osmc/internal/vsearch"

	"go.mongodb.org/mongo-driver/mongo"
)

// liveTruth grades the index against an exact scan of the documents that exist
// right now (default). RECALL_TRUTH=frozen grades against the neighbours written
// at seed time, which is only fair while none of those documents are deleted.
var liveTruth = true

func main() {
	switch env("RECALL_TRUTH", "live") {
	case "live":
		liveTruth = true
	case "frozen":
		liveTruth = false
	default:
		log.Fatalf("RECALL_TRUTH: want live or frozen")
	}
	log.Printf("recall truth: live=%t", liveTruth)
	addr := env("RECALL_ADDR", ":9948")
	interval := 10 * time.Second
	if raw := os.Getenv("RECALL_INTERVAL"); raw != "" {
		d, err := time.ParseDuration(raw)
		if err != nil {
			log.Fatalf("RECALL_INTERVAL: %v", err)
		}
		interval = d
	}
	workers := 8
	if raw := os.Getenv("RECALL_WORKERS"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 {
			log.Fatalf("RECALL_WORKERS: want a positive integer")
		}
		workers = n
	}
	goldenPath := env("GOLDEN_PATH", "/golden/golden.json")
	mongoURI := env("MONGO_URI", "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true")

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	g := waitGolden(ctx, goldenPath)
	if g == nil {
		return
	}
	client, err := vsearch.ConnectWait(ctx, mongoURI)
	if err != nil {
		log.Fatalf("mongo: %v", err)
	}
	defer client.Disconnect(context.Background())

	state := &probe{}
	go state.loop(ctx, client, goldenPath, g, workers, interval)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /metrics", state.metrics)
	mux.HandleFunc("GET /", state.metrics)
	log.Printf("recall probe listening on %s every %s (%d queries)", addr, interval, len(g.Queries))
	server := &http.Server{Addr: addr, Handler: mux}
	go func() {
		<-ctx.Done()
		shut, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = server.Shutdown(shut)
	}()
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func waitGolden(ctx context.Context, path string) *golden.File {
	for {
		g, err := golden.Load(path)
		if err == nil {
			log.Printf("loaded %d queries, seed measured %.3f at numCandidates %d", len(g.Queries), g.MeasuredRecall, g.Candidates())
			return g
		}
		log.Printf("waiting for golden set at %s: %v", path, err)
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(2 * time.Second):
		}
	}
}

type probe struct {
	mu       sync.Mutex
	recall   float64
	have     bool
	up       int
	queries  int
	errors   int
	duration float64
}

func (p *probe) loop(ctx context.Context, client *mongo.Client, goldenPath string, g *golden.File, workers int, interval time.Duration) {
	var mtime time.Time
	if info, err := os.Stat(goldenPath); err == nil {
		mtime = info.ModTime()
	}
	// Probe once before the first sleep so the panel is not empty for a full interval.
	p.run(ctx, client, g, workers)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if info, err := os.Stat(goldenPath); err == nil && info.ModTime().After(mtime) {
				if fresh, err := golden.Load(goldenPath); err == nil {
					g = fresh
					mtime = info.ModTime()
					log.Printf("reloaded golden set, %d queries", len(g.Queries))
				}
			}
			p.run(ctx, client, g, workers)
		}
	}
}

func (p *probe) run(ctx context.Context, client *mongo.Client, g *golden.File, workers int) {
	coll := client.Database(g.DB).Collection(g.Collection)
	start := time.Now()
	score, n, err := measure(ctx, coll, g, workers)
	p.mu.Lock()
	defer p.mu.Unlock()
	if err != nil {
		p.up = 0
		p.errors++
		log.Printf("probe skipped, keeping last recall: %v", err)
		return
	}
	p.recall = score
	p.have = true
	p.up = 1
	p.queries = n
	p.duration = time.Since(start).Seconds()
	log.Printf("recall@%d = %.3f over %d queries in %.1fs (numCandidates %d)", g.K, score, n, p.duration, g.Candidates())
}

// measure runs the golden set. A run where more than 10% of queries fail
// (index dropped, mongot restarting) is an error so the gauge keeps its
// previous value instead of flashing to zero.
func measure(ctx context.Context, coll *mongo.Collection, g *golden.File, workers int) (float64, int, error) {
	scores := make([]float64, len(g.Queries))
	errs := make([]error, len(g.Queries))
	sem := make(chan struct{}, workers)
	var wg sync.WaitGroup
	for i, q := range g.Queries {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, q golden.Query) {
			defer wg.Done()
			defer func() { <-sem }()
			qctx, cancel := context.WithTimeout(ctx, 8*time.Second)
			defer cancel()
			hits, err := vsearch.Search(qctx, coll, g.Index, q.Vector, g.K, g.Candidates())
			if err != nil {
				errs[i] = err
				return
			}
			truth := q.Neighbors
			if liveTruth {
				// What the top k should be among the documents that exist now.
				exact, err := vsearch.Exact(qctx, coll, g.Index, q.Vector, g.K)
				if err != nil {
					errs[i] = err
					return
				}
				truth = vsearch.IDs(exact)
			}
			scores[i] = recallmath.At(vsearch.IDs(hits), truth, g.K)
		}(i, q)
	}
	wg.Wait()

	ok := make([]float64, 0, len(scores))
	failed := 0
	var first error
	for i, err := range errs {
		if err != nil {
			failed++
			if first == nil {
				first = err
			}
			continue
		}
		ok = append(ok, scores[i])
	}
	if len(g.Queries) > 0 && failed*10 > len(g.Queries) {
		return 0, len(ok), fmt.Errorf("%d/%d queries failed: %w", failed, len(g.Queries), first)
	}
	return recallmath.Mean(ok), len(ok), nil
}

func (p *probe) metrics(w http.ResponseWriter, r *http.Request) {
	p.mu.Lock()
	defer p.mu.Unlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	fmt.Fprintf(w, "# HELP vector_search_recall_at_10 Mean recall@k of the golden set against the live index.\n")
	fmt.Fprintf(w, "# TYPE vector_search_recall_at_10 gauge\n")
	if p.have {
		fmt.Fprintf(w, "vector_search_recall_at_10 %.6f\n", p.recall)
	}
	fmt.Fprintf(w, "# HELP vector_search_recall_up 1 when the last probe finished, 0 when the index did not answer.\n")
	fmt.Fprintf(w, "# TYPE vector_search_recall_up gauge\n")
	fmt.Fprintf(w, "vector_search_recall_up %d\n", p.up)
	fmt.Fprintf(w, "# HELP vector_search_recall_queries Queries that contributed to the last successful probe.\n")
	fmt.Fprintf(w, "# TYPE vector_search_recall_queries gauge\n")
	fmt.Fprintf(w, "vector_search_recall_queries %d\n", p.queries)
	fmt.Fprintf(w, "# HELP vector_search_recall_duration_seconds Wall time of the last successful probe.\n")
	fmt.Fprintf(w, "# TYPE vector_search_recall_duration_seconds gauge\n")
	fmt.Fprintf(w, "vector_search_recall_duration_seconds %.3f\n", p.duration)
	fmt.Fprintf(w, "# HELP vector_search_recall_errors_total Probes discarded because too many queries failed.\n")
	fmt.Fprintf(w, "# TYPE vector_search_recall_errors_total counter\n")
	fmt.Fprintf(w, "vector_search_recall_errors_total %d\n", p.errors)
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
