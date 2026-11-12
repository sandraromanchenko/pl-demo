// Package golden loads the offline query set shared by the recall probe,
// the RAG app, and the failure script.
package golden

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
)

// File is written by osmc/seed.py once the index is READY and recall has
// been calibrated. Query vectors are the embedded questions; neighbors are
// the exact top-k document ids at that moment.
type File struct {
	DB             string  `json:"db"`
	Collection     string  `json:"collection"`
	Index          string  `json:"index"`
	K              int     `json:"k"`
	NumCandidates  int     `json:"numCandidates"`
	Dims           int     `json:"dims"`
	MeasuredRecall float64 `json:"measuredRecall"`
	Queries        []Query `json:"queries"`
}

// Query is one golden question. Vector is what the probe searches with, so
// the live loop does not call the embedding model.
type Query struct {
	ID        string    `json:"id"`
	Text      string    `json:"text"`
	Vector    []float64 `json:"vector"`
	Neighbors []string  `json:"neighbors"`
}

// IndexSpec is the createSearchIndexes payload, so reindex rebuilds the
// same definition the seed measured against.
type IndexSpec struct {
	DB         string         `json:"db"`
	Collection string         `json:"collection"`
	Name       string         `json:"name"`
	Definition map[string]any `json:"definition"`
}

// Load reads a golden file from path.
func Load(path string) (*File, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f File
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	if f.K <= 0 {
		return nil, fmt.Errorf("%s: k must be positive", path)
	}
	if len(f.Queries) == 0 {
		return nil, fmt.Errorf("%s: no queries", path)
	}
	return &f, nil
}

// LoadIndex reads the vector index definition saved next to the golden file.
func LoadIndex(path string) (*IndexSpec, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var spec IndexSpec
	if err := json.Unmarshal(raw, &spec); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	if spec.Name == "" || spec.Collection == "" || spec.Definition == nil {
		return nil, fmt.Errorf("%s: incomplete index spec", path)
	}
	return &spec, nil
}

// Candidates is the HNSW beam the probe and the RAG app share.
// NUM_CANDIDATES overrides the value calibrated at seed time.
func (f *File) Candidates() int {
	if raw := os.Getenv("NUM_CANDIDATES"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err == nil && n >= f.K {
			return n
		}
	}
	if f.NumCandidates >= f.K {
		return f.NumCandidates
	}
	return f.K * 4
}
