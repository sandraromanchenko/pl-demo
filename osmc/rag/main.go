package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"pl-demo/osmc/internal/golden"
	"pl-demo/osmc/internal/vsearch"

	"go.mongodb.org/mongo-driver/mongo"
)

func main() {
	addr := env("RAG_ADDR", ":8090")
	mongoURI := env("MONGO_URI", "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true")
	ollamaURL := strings.TrimRight(env("OLLAMA_URL", "http://ollama:11434"), "/")
	vllmURL := strings.TrimRight(env("VLLM_URL", "http://vllm:8000"), "/")
	embedModel := env("EMBED_MODEL", "bge-small")
	chatModel := env("VLLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
	goldenPath := env("GOLDEN_PATH", "/golden/golden.json")

	ctx := context.Background()
	client, err := vsearch.ConnectWait(ctx, mongoURI)
	if err != nil {
		log.Fatalf("mongo: %v", err)
	}
	defer client.Disconnect(context.Background())

	srv := &server{
		client:     client,
		mongoURI:   mongoURI,
		ollamaURL:  ollamaURL,
		vllmURL:    vllmURL,
		embedModel: embedModel,
		chatModel:  chatModel,
		goldenPath: goldenPath,
		dbName:     env("MONGO_DB", "boardgames"),
		collName:   env("MONGO_COLLECTION", "catalog"),
		indexName:  env("VECTOR_INDEX", "vec_osmc"),
		http:       &http.Client{Timeout: 180 * time.Second},
	}
	mux := http.NewServeMux()
	// The page is the "Ask" tab of the search app on :8081, which proxies /rag/ to this API.
	mux.HandleFunc("GET /health", srv.health)
	mux.HandleFunc("GET /ask", srv.ask)
	mux.HandleFunc("POST /ask", srv.ask)
	log.Printf("rag listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

type server struct {
	client     *mongo.Client
	mongoURI   string
	ollamaURL  string
	vllmURL    string
	embedModel string
	chatModel  string
	goldenPath string
	dbName     string
	collName   string
	indexName  string
	http       *http.Client
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.client.Ping(ctx, nil); err != nil {
		http.Error(w, err.Error(), http.StatusServiceUnavailable)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

type askRequest struct {
	Q string `json:"q"`
}

type source struct {
	ID    string  `json:"id"`
	Title string  `json:"title"`
	Text  string  `json:"text"`
	Score float64 `json:"score"`
}

type askResponse struct {
	Answer   string   `json:"answer"`
	Sources  []source `json:"sources"`
	EmbedMs  int64    `json:"embedMs"`
	SearchMs int64    `json:"searchMs"`
	LlmMs    int64    `json:"llmMs"`
}

func (s *server) ask(w http.ResponseWriter, r *http.Request) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if q == "" && r.Body != nil {
		var req askRequest
		if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&req); err == nil {
			q = strings.TrimSpace(req.Q)
		}
	}
	if q == "" {
		http.Error(w, "pass q as a query parameter or json {\"q\": \"...\"}", http.StatusBadRequest)
		return
	}

	limit := 4
	numCandidates := 40
	index := s.indexName
	if g, err := golden.Load(s.goldenPath); err == nil {
		numCandidates = g.Candidates()
		if g.Index != "" {
			index = g.Index
		}
	}

	embedStart := time.Now()
	vector, err := s.embed(r.Context(), q)
	embedMs := time.Since(embedStart).Milliseconds()
	if err != nil {
		http.Error(w, "embed: "+err.Error(), http.StatusBadGateway)
		return
	}

	searchStart := time.Now()
	sctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	hits, err := vsearch.Search(sctx, s.client.Database(s.dbName).Collection(s.collName), index, vector, limit, numCandidates)
	cancel()
	searchMs := time.Since(searchStart).Milliseconds()
	if err != nil {
		http.Error(w, "search: "+err.Error(), http.StatusBadGateway)
		return
	}

	llmStart := time.Now()
	answer, err := s.complete(r.Context(), q, hits)
	llmMs := time.Since(llmStart).Milliseconds()
	if err != nil {
		http.Error(w, "vllm: "+err.Error(), http.StatusBadGateway)
		return
	}

	sources := make([]source, len(hits))
	for i, h := range hits {
		text := h.Text
		if len(text) > 320 {
			text = text[:320] + "…"
		}
		sources[i] = source{ID: h.ID, Title: h.Title, Text: text, Score: h.Score}
	}
	writeJSON(w, http.StatusOK, askResponse{
		Answer: answer, Sources: sources,
		EmbedMs: embedMs, SearchMs: searchMs, LlmMs: llmMs,
	})
}

// currentEmbedModel is the model questions are embedded with right now. `swap-model`
// writes a name into the golden volume; without that file the EMBED_MODEL setting applies.
func (s *server) currentEmbedModel() string {
	if b, err := os.ReadFile(env("QUERY_MODEL_FILE", "/golden/query_model")); err == nil {
		if name := strings.TrimSpace(string(b)); name != "" {
			return name
		}
	}
	return s.embedModel
}

func (s *server) embed(ctx context.Context, text string) ([]float64, error) {
	body, _ := json.Marshal(map[string]any{"model": s.currentEmbedModel(), "input": text})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.ollamaURL+"/api/embed", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ollama %s: %s", resp.Status, raw)
	}
	var parsed struct {
		Embeddings [][]float64 `json:"embeddings"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, err
	}
	if len(parsed.Embeddings) == 0 || len(parsed.Embeddings[0]) == 0 {
		return nil, fmt.Errorf("ollama returned no embedding")
	}
	return parsed.Embeddings[0], nil
}

func (s *server) complete(ctx context.Context, question string, hits []vsearch.Hit) (string, error) {
	var b strings.Builder
	for i, h := range hits {
		text := h.Text
		if len(text) > 500 {
			text = text[:500]
		}
		fmt.Fprintf(&b, "[%d] %s\n%s\n\n", i+1, h.Title, text)
	}
	if b.Len() == 0 {
		b.WriteString("(no passages retrieved)\n")
	}
	payload, _ := json.Marshal(map[string]any{
		"model": s.chatModel,
		"messages": []map[string]string{
			{"role": "system", "content": "Answer the question using only the retrieved passages. List every passage that fits the question, at most three, one per line, in the form: <game name>: <one sentence from its passage>. If only one passage fits, list one. If none fits, say so. Do not invent a game that is not in the passages."},
			{"role": "user", "content": "Passages:\n" + b.String() + "\nQuestion: " + question},
		},
		"max_tokens":  300,
		"temperature": 0,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.vllmURL+"/v1/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("%s: %s", resp.Status, raw)
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return "", err
	}
	if len(parsed.Choices) == 0 {
		return "", fmt.Errorf("vllm returned no choices")
	}
	return strings.TrimSpace(parsed.Choices[0].Message.Content), nil
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
