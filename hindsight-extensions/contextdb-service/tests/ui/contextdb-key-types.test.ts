import { describe, expectTypeOf, it } from "vitest";
import type {
  ContextDBKeyEditable,
  ContextDBKeyIssued,
  ContextDBKeyMetadata,
  KeyAuthorizationInput,
  KeyPermission,
} from "@/lib/contextdb-api";

describe("management Key response projections", () => {
  it("requires a secret only for issuance and usage statistics only for the list", () => {
    expectTypeOf<ContextDBKeyIssued["secret"]>().toEqualTypeOf<string>();
    expectTypeOf<ContextDBKeyMetadata["last_used_at"]>().toEqualTypeOf<string | null>();
    expectTypeOf<Extract<"secret", keyof ContextDBKeyEditable>>().toEqualTypeOf<never>();
    expectTypeOf<Extract<"last_used_at", keyof ContextDBKeyIssued>>().toEqualTypeOf<never>();
    expectTypeOf<Extract<"last_used_at", keyof ContextDBKeyEditable>>().toEqualTypeOf<never>();
    expectTypeOf<ContextDBKeyEditable["display_key"]>().toEqualTypeOf<string | null | undefined>();
    expectTypeOf<ContextDBKeyIssued>().toExtend<ContextDBKeyEditable>();
    expectTypeOf<ContextDBKeyMetadata>().toExtend<ContextDBKeyEditable>();
  });
  it("keeps explicit read/write permissions and immutable selected workspace identities", () => {
    expectTypeOf<KeyPermission>().toEqualTypeOf<"read" | "read_write">();
    type SelectedInput = Extract<KeyAuthorizationInput, { mode: "selected" }>;
    expectTypeOf<SelectedInput["workspaces"][number]["workspace_id"]>().toEqualTypeOf<string>();
  });
});
