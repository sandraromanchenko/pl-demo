// Package recallmath is the recall@k calculation, kept free of MongoDB so
// it can be tested on its own.
package recallmath

// At returns |got ∩ truth| / k. Extra hits and rank order do not count.
// truth is the exact top-k; got is whatever the live index returned.
func At(got, truth []string, k int) float64 {
	if k <= 0 {
		return 0
	}
	want := make(map[string]struct{}, len(truth))
	for _, id := range truth {
		want[id] = struct{}{}
	}
	n := 0
	seen := make(map[string]struct{}, len(got))
	for _, id := range got {
		if _, dup := seen[id]; dup {
			continue
		}
		seen[id] = struct{}{}
		if _, ok := want[id]; ok {
			n++
		}
	}
	return float64(n) / float64(k)
}

// Mean is the unweighted mean of per-query recall@k.
func Mean(scores []float64) float64 {
	if len(scores) == 0 {
		return 0
	}
	var sum float64
	for _, s := range scores {
		sum += s
	}
	return sum / float64(len(scores))
}
