// Package vsearch runs $vectorSearch against a precomputed-vector index.
package vsearch

import (
	"context"
	"fmt"
	"log"
	"time"

	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
)

// Hit is one neighbor returned by the live index.
type Hit struct {
	ID    string
	Title string
	Text  string
	Score float64
}

// Search runs an approximate vector query. numCandidates must be >= limit;
// that beam is the same one the recall probe uses.
func Search(ctx context.Context, coll *mongo.Collection, index string, vector []float64, limit, numCandidates int) ([]Hit, error) {
	if numCandidates < limit {
		numCandidates = limit
	}
	cur, err := coll.Aggregate(ctx, mongo.Pipeline{
		bson.D{{Key: "$vectorSearch", Value: bson.D{
			{Key: "index", Value: index},
			{Key: "path", Value: "embedding"},
			{Key: "queryVector", Value: vector},
			{Key: "numCandidates", Value: numCandidates},
			{Key: "limit", Value: limit},
		}}},
		bson.D{{Key: "$project", Value: bson.D{
			{Key: "_id", Value: 1},
			{Key: "title", Value: 1},
			{Key: "text", Value: 1},
			{Key: "score", Value: bson.D{{Key: "$meta", Value: "vectorSearchScore"}}},
		}}},
	})
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var hits []Hit
	for cur.Next(ctx) {
		var row struct {
			ID    string  `bson:"_id"`
			Title string  `bson:"title"`
			Text  string  `bson:"text"`
			Score float64 `bson:"score"`
		}
		if err := cur.Decode(&row); err != nil {
			return nil, err
		}
		hits = append(hits, Hit{ID: row.ID, Title: row.Title, Text: row.Text, Score: row.Score})
	}
	if err := cur.Err(); err != nil {
		return nil, err
	}
	return hits, nil
}

// Exact runs a brute-force query over the live documents ($vectorSearch with
// exact: true). It is the ground truth for "what should the top k be right now".
func Exact(ctx context.Context, coll *mongo.Collection, index string, vector []float64, limit int) ([]Hit, error) {
	cur, err := coll.Aggregate(ctx, mongo.Pipeline{
		bson.D{{Key: "$vectorSearch", Value: bson.D{
			{Key: "index", Value: index},
			{Key: "path", Value: "embedding"},
			{Key: "queryVector", Value: vector},
			{Key: "exact", Value: true},
			{Key: "limit", Value: limit},
		}}},
		bson.D{{Key: "$project", Value: bson.D{{Key: "_id", Value: 1}}}},
	})
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var hits []Hit
	for cur.Next(ctx) {
		var row struct {
			ID string `bson:"_id"`
		}
		if err := cur.Decode(&row); err != nil {
			return nil, err
		}
		hits = append(hits, Hit{ID: row.ID})
	}
	if err := cur.Err(); err != nil {
		return nil, err
	}
	return hits, nil
}

// IDs extracts document ids in rank order.
func IDs(hits []Hit) []string {
	ids := make([]string, len(hits))
	for i, h := range hits {
		ids[i] = h.ID
	}
	return ids
}

// Connect pings MongoDB and returns a client. Caller closes it.
func Connect(ctx context.Context, uri string) (*mongo.Client, error) {
	client, err := mongo.Connect(ctx, clientOptions(uri))
	if err != nil {
		return nil, err
	}
	if err := client.Ping(ctx, nil); err != nil {
		_ = client.Disconnect(context.Background())
		return nil, fmt.Errorf("ping: %w", err)
	}
	return client, nil
}

// ConnectWait retries until MongoDB answers or ctx is cancelled.
func ConnectWait(ctx context.Context, uri string) (*mongo.Client, error) {
	var last error
	for {
		client, err := Connect(ctx, uri)
		if err == nil {
			return client, nil
		}
		last = err
		log.Printf("waiting for mongo: %v", err)
		select {
		case <-ctx.Done():
			if last != nil {
				return nil, last
			}
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}
