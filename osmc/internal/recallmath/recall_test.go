package recallmath

import "testing"

func TestAt(t *testing.T) {
	truth := []string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"}
	got := []string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "z"}
	if got, want := At(got, truth, 10), 0.9; got != want {
		t.Fatalf("recall = %v, want %v", got, want)
	}
}

func TestAtIgnoresOrderAndDuplicates(t *testing.T) {
	truth := []string{"a", "b"}
	got := []string{"b", "b", "a"}
	if got, want := At(got, truth, 2), 1.0; got != want {
		t.Fatalf("recall = %v, want %v", got, want)
	}
}

func TestMean(t *testing.T) {
	if got, want := Mean([]float64{1, 0.5}), 0.75; got != want {
		t.Fatalf("mean = %v, want %v", got, want)
	}
	if Mean(nil) != 0 {
		t.Fatal("empty mean should be 0")
	}
}
