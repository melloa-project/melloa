# Owner export

The Data & safety screen can build a readable ZIP after fresh owner confirmation. The archive is a
provider-independent portability copy: its contents are ordinary versioned JSON, not a provider SDK
format. Melloa does not currently provide an importer, so the ZIP is not a restore bundle.

The browser download is **not encrypted**. Store it as private owner data. Encrypted database backups
are separate and may retain older data according to their independently configured expiry.

## Current format

`melloa-owner-export-v2` contains:

- `manifest.json`: format version, export identity, generation time, owner identity, encryption and
  coverage disclosures, known limitations, byte lengths, and SHA-256 hashes for each data file;
- `conversations.json`: active threads, every retained message version, correction links, answers,
  turns, reply-processing history, and completed-answer retrieval/model provenance;
- `memories.json`: retained memory values, current state, append-only state changes, correction and
  provenance edges, and content-free tombstones for memory values already deleted.

Melloa assembles the files, writes the manifest hashes, reopens the ZIP, and verifies its structure
and exact contents before returning it.

## Honest limits

The current archive does not include:

- conversation content that the owner already deleted, or conversation deletion receipts;
- full provider output from failed reply attempts (recorded outcomes, possible external destination,
  and disclosed-memory IDs are included);
- login sessions, authentication secrets, provider credentials, or signed-in browser history;
- general system events or audit-chain records;
- database backups or their encryption keys.

Corrected conversation wording remains in the export with `corrects_message_id` provenance even
though the ordinary transcript shows only the active wording and answer. A deleted memory value is
absent from `memories.json`, but a copy may remain in a conversation's completed-answer provenance
if that answer used it. Deleting that conversation removes its active provenance data; encrypted
backups may still retain an older copy within their separately configured limits.
