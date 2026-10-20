TL;DR: Verbatim legacy roadmap: 9. Persistence, backup, and migration.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 9. Persistence, backup, and migration

Store source paths relative to the managed workspace and verify hashes when restoring or investigating corruption. Source bytes are immutable after registration; extraction corrections create processed versions.

Use SQLite's backup API or another documented consistent snapshot method. Read the source/asset list from the snapshot and copy exactly its referenced immutable files. Include schema/contract versions and hashes in the export manifest. Test database integrity, foreign-key consistency, and source-reference resolution after restoring into a new path.

Do not commit a live learner database or uploaded course materials to the code repository as the synchronization mechanism. Snapshot transfer supports moving workspaces; simultaneous remote use requires a single service owning the database and is deferred. A temporary cloud working directory is not durable persistence unless an explicit save/restore integration supplies it.

