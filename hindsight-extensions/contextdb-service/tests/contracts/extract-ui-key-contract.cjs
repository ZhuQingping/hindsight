// Deliberately limited to the three UI Key projections, not a TS schema generator.
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { createRequire } = require("node:module");
const root = resolve(process.argv[2]);
const ts = createRequire(resolve(root, "hindsight-control-plane/package.json"))("typescript");
const source = ts.createSourceFile(
  "contextdb-api.ts",
  readFileSync(resolve(root, "hindsight-control-plane/src/lib/contextdb-api.ts"), "utf8"),
  ts.ScriptTarget.Latest,
  true
);
const declarations = new Map(source.statements.filter((n) => n.name).map((n) => [n.name.text, n]));
function typeOf(node) {
  if (node.kind === ts.SyntaxKind.StringKeyword) return { type: "string", nullable: false };
  if (node.kind === ts.SyntaxKind.NumberKeyword) return { type: "number", nullable: false };
  if (
    ts.isUnionTypeNode(node) &&
    node.types.length === 2 &&
    node.types.some(
      (n) => n.kind === ts.SyntaxKind.LiteralType && n.literal.kind === ts.SyntaxKind.NullKeyword
    )
  ) {
    return {
      ...typeOf(
        node.types.find(
          (n) => !(ts.isLiteralTypeNode(n) && n.literal.kind === ts.SyntaxKind.NullKeyword)
        )
      ),
      nullable: true,
    };
  }
  if (ts.isTypeReferenceNode(node) && node.getText(source) === "KeyAuthorization")
    return { type: "authorization", nullable: false };
  throw new Error(`Unsupported Key projection type: ${node.getText(source)}`);
}
const allowed = new Set(["ContextDBKeyEditable", "ContextDBKeyMetadata", "ContextDBKeyIssued"]);
function fieldsFor(name, visiting = new Set()) {
  if (!allowed.has(name) || visiting.has(name))
    throw new Error(`Unsupported Key heritage: ${name}`);
  const node = declarations.get(name);
  if (!node || !ts.isInterfaceDeclaration(node)) throw new Error(`Expected interface ${name}`);
  visiting.add(name);
  const fields = {};
  for (const clause of node.heritageClauses || []) {
    if (clause.token !== ts.SyntaxKind.ExtendsKeyword) throw new Error("Only extends is supported");
    for (const base of clause.types)
      Object.assign(fields, fieldsFor(base.getText(source), new Set(visiting)));
  }
  for (const member of node.members) {
    if (!ts.isPropertySignature(member) || !member.type || !ts.isIdentifier(member.name))
      throw new Error(`Unsupported member in ${name}`);
    if (fields[member.name.text]) throw new Error(`Overridden field ${member.name.text}`);
    fields[member.name.text] = { ...typeOf(member.type), required: !member.questionToken };
  }
  return fields;
}
const permission = declarations.get("KeyPermission");
if (
  !permission ||
  !ts.isTypeAliasDeclaration(permission) ||
  !ts.isUnionTypeNode(permission.type) ||
  !permission.type.types.every((n) => ts.isLiteralTypeNode(n) && ts.isStringLiteral(n.literal))
)
  throw new Error("Expected a literal KeyPermission union");
console.log(
  JSON.stringify({
    projections: Object.fromEntries([...allowed].map((name) => [name, fieldsFor(name)])),
    permissions: permission.type.types.map((n) => n.literal.text).sort(),
  })
);
