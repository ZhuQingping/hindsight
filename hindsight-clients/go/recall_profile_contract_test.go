package contextbase

import (
	"encoding/json"
	"testing"
)

func TestRecallProfileContract(t *testing.T) {
	request := NewRecallRequest("art")
	body, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	var object map[string]interface{}
	if err := json.Unmarshal(body, &object); err != nil {
		t.Fatal(err)
	}
	if _, present := object["recall_profile"]; present {
		t.Fatal("default request introduced profile field")
	}
	request.SetRecallProfile("locomo")
	body, err = json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(body, &object); err != nil {
		t.Fatal(err)
	}
	if object["recall_profile"] != "locomo" {
		t.Fatal("explicit profile lost")
	}
	var response RecallResponse
	if err := json.Unmarshal([]byte(`{"results":[]}`), &response); err != nil {
		t.Fatal(err)
	}
	if response.HasRecallContext() {
		t.Fatal("old response acquired a profile")
	}
}
