package hindsight

import "testing"

// Existing consumer calls must compile after regeneration; nullable array items
// would change these setter signatures to slices of pointers.
func TestExistingArrayModelConsumerCompatibility(t *testing.T) {
	memory := MemoryUnitListItem{}
	memory.SetSourceMemoryIds([]string{"source-memory"})
	var sources []string = memory.GetSourceMemoryIds()
	if len(sources) != 1 || sources[0] != "source-memory" {
		t.Fatal("source memory identifiers did not round trip")
	}
	template := BankTemplateConfig{}
	template.SetObservationScopeLimits([]map[string]interface{}{{"limit": 1}})
	var scopes []map[string]interface{} = template.GetObservationScopeLimits()
	if len(scopes) != 1 {
		t.Fatal("scope limits did not round trip")
	}
	delta := MentalModelDeltaOperations{}
	delta.SetApplied([]map[string]interface{}{{"op": "add"}})
	delta.SetSkipped([]map[string]interface{}{})
	var applied []map[string]interface{} = delta.GetApplied()
	if len(applied) != 1 {
		t.Fatal("delta operations did not round trip")
	}
}
