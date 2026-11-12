package vsearch

import (
	"time"

	"go.mongodb.org/mongo-driver/mongo/options"
)

func clientOptions(uri string) *options.ClientOptions {
	return options.Client().
		ApplyURI(uri).
		SetServerSelectionTimeout(5 * time.Second).
		SetConnectTimeout(5 * time.Second)
}
