package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"

	contextbase "github.com/vectorize-io/hindsight/hindsight-clients/go"
)

func main() {
	apiURL := os.Getenv("CONTEXTBASE_API_URL")
	if apiURL == "" {
		apiURL = "http://localhost:8888"
	}

	cfg := contextbase.NewConfiguration()
	cfg.Servers = contextbase.ServerConfigurations{{URL: apiURL}}
	client := contextbase.NewAPIClient(cfg)
	ctx := context.Background()

	// [docs:document-retain]
	// Retain with document ID
	docID := "meeting-2024-03-15"
	client.MemoryAPI.RetainMemories(ctx, "my-bank").
		RetainRequest(contextbase.RetainRequest{
			Items: []contextbase.MemoryItem{
				{
					Content:    contextbase.TextContent("Alice presented the Q4 roadmap..."),
					DocumentId: *contextbase.NewNullableString(&docID),
				},
			},
		}).Execute()
	// [/docs:document-retain]

	// [docs:document-update]
	// Original
	planDoc := "project-plan"
	client.MemoryAPI.RetainMemories(ctx, "my-bank").
		RetainRequest(contextbase.RetainRequest{
			Items: []contextbase.MemoryItem{
				{
					Content:    contextbase.TextContent("Project deadline: March 31"),
					DocumentId: *contextbase.NewNullableString(&planDoc),
				},
			},
		}).Execute()

	// Update (deletes old facts, creates new ones)
	client.MemoryAPI.RetainMemories(ctx, "my-bank").
		RetainRequest(contextbase.RetainRequest{
			Items: []contextbase.MemoryItem{
				{
					Content:    contextbase.TextContent("Project deadline: April 15 (extended)"),
					DocumentId: *contextbase.NewNullableString(&planDoc),
				},
			},
		}).Execute()
	// [/docs:document-update]

	// [docs:document-get]
	doc, _, err := client.DocumentsAPI.GetDocument(ctx, "my-bank", "meeting-2024-03-15").Execute()
	if err != nil {
		log.Fatalf("Failed to get document: %v", err)
	}
	fmt.Printf("Document ID: %s\n", doc.GetId())
	fmt.Printf("Memory units: %d\n", doc.GetMemoryUnitCount())
	// [/docs:document-get]

	// [docs:document-update-tags]
	// Replace the document's tags (the full set it should end up with)
	updateResult, _, err := client.DocumentsAPI.UpdateDocument(ctx, "my-bank", "meeting-2024-03-15").
		UpdateDocumentRequest(contextbase.UpdateDocumentRequest{Tags: []string{"team-a", "team-b"}}).
		Execute()
	if err != nil {
		log.Fatalf("Failed to update document: %v", err)
	}
	fmt.Printf("Updated: %v\n", updateResult.GetSuccess())

	// Remove all tags (make document visible everywhere). Pass an empty slice, not nil:
	// a nil slice is left out of the request, and the server rejects an update with no tags.
	client.DocumentsAPI.UpdateDocument(ctx, "my-bank", "meeting-2024-03-15").
		UpdateDocumentRequest(contextbase.UpdateDocumentRequest{Tags: []string{}}).
		Execute()
	// [/docs:document-update-tags]

	cleared, _, err := client.DocumentsAPI.GetDocument(ctx, "my-bank", "meeting-2024-03-15").Execute()
	if err != nil || len(cleared.GetTags()) != 0 {
		log.Fatalf("Expected no tags after clearing, got %v (err %v)", cleared.GetTags(), err)
	}

	// [docs:document-delete]
	client.DocumentsAPI.DeleteDocument(ctx, "my-bank", "meeting-2024-03-15").Execute()
	// [/docs:document-delete]

	// [docs:document-list]
	// List all documents
	docs, _, err := client.DocumentsAPI.ListDocuments(ctx, "my-bank").Execute()
	if err != nil {
		log.Fatalf("Failed to list documents: %v", err)
	}
	for _, d := range docs.Items {
		fmt.Printf("%s: %d memories\n", d.Id, d.GetMemoryUnitCount())
	}
	// [/docs:document-list]

	// Cleanup (not shown in docs)
	req, _ := http.NewRequest("DELETE", fmt.Sprintf("%s/v1/default/banks/my-bank", apiURL), nil)
	http.DefaultClient.Do(req)

	fmt.Println("documents.go: All examples passed")
}
