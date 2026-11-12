// Command reindex drops the vector index and builds it again from the
// documents that are still in the collection. That is the cure the talk
// demonstrates: same vectors, a clean HNSW graph, recall returns.
package main

import (
	"context"
	"log"
	"math"
	"os"
	"time"

	"pl-demo/osmc/internal/golden"
	"pl-demo/osmc/internal/vsearch"

	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
)

func main() {
	indexPath := env("INDEX_PATH", "/golden/index.json")
	mongoURI := env("MONGO_URI", "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true")

	spec, err := golden.LoadIndex(indexPath)
	if err != nil {
		log.Fatalf("index spec: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	client, err := vsearch.ConnectWait(ctx, mongoURI)
	if err != nil {
		log.Fatalf("mongo: %v", err)
	}
	defer client.Disconnect(context.Background())
	db := client.Database(spec.DB)

	log.Printf("dropping search index %s.%s", spec.Collection, spec.Name)
	dropErr := db.RunCommand(ctx, bson.D{
		{Key: "dropSearchIndex", Value: spec.Collection},
		{Key: "name", Value: spec.Name},
	}).Err()
	if dropErr != nil {
		log.Printf("drop returned %v (continuing to create)", dropErr)
	}

	log.Printf("creating search index %s", spec.Name)
	if err := db.RunCommand(ctx, bson.D{
		{Key: "createSearchIndexes", Value: spec.Collection},
		{Key: "indexes", Value: bson.A{bson.D{
			{Key: "name", Value: spec.Name},
			{Key: "type", Value: "vectorSearch"},
			{Key: "definition", Value: normalize(spec.Definition)},
		}}},
	}).Err(); err != nil {
		log.Fatalf("create: %v", err)
	}

	coll := db.Collection(spec.Collection)
	deadline := time.Now().Add(15 * time.Minute)
	for {
		status, err := indexStatus(ctx, coll, spec.Name)
		if err != nil {
			log.Printf("status: %v", err)
		} else {
			log.Printf("index %s status %s", spec.Name, status)
			if status == "READY" {
				log.Printf("reindex complete")
				return
			}
		}
		if time.Now().After(deadline) {
			log.Fatal("timed out waiting for READY")
		}
		time.Sleep(2 * time.Second)
	}
}

func indexStatus(ctx context.Context, coll *mongo.Collection, name string) (string, error) {
	cur, err := coll.Aggregate(ctx, mongo.Pipeline{
		bson.D{{Key: "$listSearchIndexes", Value: bson.D{{Key: "name", Value: name}}}},
	})
	if err != nil {
		return "", err
	}
	defer cur.Close(ctx)
	if !cur.Next(ctx) {
		if err := cur.Err(); err != nil {
			return "", err
		}
		return "MISSING", nil
	}
	var row struct {
		Status string `bson:"status"`
	}
	if err := cur.Decode(&row); err != nil {
		return "", err
	}
	return row.Status, nil
}

// normalize turns JSON numbers into ints so mongod accepts numDimensions.
func normalize(v any) any {
	switch t := v.(type) {
	case map[string]any:
		m := bson.M{}
		for k, val := range t {
			m[k] = normalize(val)
		}
		return m
	case bson.M:
		m := bson.M{}
		for k, val := range t {
			m[k] = normalize(val)
		}
		return m
	case []any:
		a := make(bson.A, len(t))
		for i, val := range t {
			a[i] = normalize(val)
		}
		return a
	case float64:
		if t == math.Trunc(t) && t <= math.MaxInt32 && t >= math.MinInt32 {
			return int32(t)
		}
		return t
	default:
		return v
	}
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
