"""Every table of the AI search index, rag_index.db, in one place (ARC-24).

The index can be rebuilt from the files (db_schema.REBUILDABLE), so its tables are created
with IF NOT EXISTS by the code that first needs them: the engine at start (INDEX), and tags,
the CJK keyword index, photo vectors, captions and OCR when their feature first runs. Columns
added later go in db_schema.COLUMN_UPGRADES. Nothing outside the schema modules creates a
table (tests/test_arc24_schema_home.py).
"""

META = "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)"

INDEX = """
CREATE TABLE IF NOT EXISTS indexed_files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_path TEXT UNIQUE NOT NULL,
    parent_dir TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_ext TEXT NOT NULL,
    modality TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'generic',
    doc_title TEXT NOT NULL DEFAULT '',
    doc_metadata_json TEXT NOT NULL DEFAULT '{}',
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    backing_dev TEXT NOT NULL DEFAULT '',
    pool_id TEXT NOT NULL DEFAULT '',
    share_name TEXT NOT NULL DEFAULT '',
    visibility_tier TEXT NOT NULL DEFAULT 'public_share',
    owner_username TEXT NOT NULL DEFAULT '',
    allowed_users_csv TEXT NOT NULL DEFAULT '*',
    parse_status TEXT NOT NULL DEFAULT 'ok',
    index_version INTEGER NOT NULL DEFAULT 3,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL NOT NULL,
    last_verified_at REAL NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'zett_lexical_384d'
);

CREATE INDEX IF NOT EXISTS idx_files_lookup ON indexed_files(canonical_path, mtime_ns, size_bytes);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON indexed_files(sha256_hash, size_bytes);
CREATE INDEX IF NOT EXISTS idx_files_rbac ON indexed_files(visibility_tier, owner_username, share_name);
CREATE INDEX IF NOT EXISTS idx_files_modality_type ON indexed_files(modality, doc_type);
CREATE INDEX IF NOT EXISTS idx_files_parent ON indexed_files(parent_dir);
CREATE INDEX IF NOT EXISTS idx_files_ext ON indexed_files(file_ext);
-- the newest readable files first without sorting the whole index (PERF-24); partial,
-- so it doesn't take the plan from narrower indexes like idx_files_fallback_vectors
CREATE INDEX IF NOT EXISTS idx_files_ok_mtime ON indexed_files(mtime_ns DESC) WHERE parse_status = 'ok';
-- auto-tags for the document filters (B8, rag_tags.SCHEMA)
CREATE TABLE IF NOT EXISTS doc_tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (file_id, tag));
CREATE INDEX IF NOT EXISTS idx_doc_tags_tag ON doc_tags(tag, file_id);
CREATE TABLE IF NOT EXISTS doc_tags_done (file_id INTEGER PRIMARY KEY);
-- the fallback re-embed check runs every 5 minutes; without this it scanned every file (PERF-5)
CREATE INDEX IF NOT EXISTS idx_files_fallback_vectors ON indexed_files(file_id)
    WHERE parse_status = 'ok' AND embedding_model = 'zett_lexical_384d';

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES indexed_files(file_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    parent_chunk_id INTEGER DEFAULT NULL,
    chunk_level TEXT NOT NULL DEFAULT 'child',
    source_modality TEXT NOT NULL DEFAULT 'document',
    file_name TEXT NOT NULL DEFAULT '',
    doc_type TEXT NOT NULL DEFAULT 'generic',
    heading_context TEXT NOT NULL DEFAULT '',
    structural_context TEXT NOT NULL DEFAULT '',
    chunk_text TEXT NOT NULL,
    raw_chunk_text TEXT NOT NULL DEFAULT '',
    doc_metadata_json TEXT NOT NULL DEFAULT '{}',
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    line_start INTEGER NOT NULL DEFAULT 1,
    line_end INTEGER NOT NULL DEFAULT 1,
    page INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT NOT NULL DEFAULT 'zettnas-unified-384-v2',
    embedding_dim INTEGER NOT NULL DEFAULT 384,
    embedding_f32 BLOB NOT NULL,
    visibility_tier TEXT NOT NULL DEFAULT 'public_share',
    owner_username TEXT NOT NULL DEFAULT '',
    share_name TEXT NOT NULL DEFAULT '',
    allowed_users_csv TEXT NOT NULL DEFAULT '*',
    UNIQUE(file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON document_chunks(file_id);
-- Lets search pick its newest chunks without reading every chunk row
CREATE INDEX IF NOT EXISTS idx_chunks_file_level ON document_chunks(file_id, chunk_level);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON document_chunks(file_id, parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunks_level ON document_chunks(chunk_level);
CREATE INDEX IF NOT EXISTS idx_chunks_rbac ON document_chunks(visibility_tier, owner_username, share_name);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
    file_name,
    heading_context,
    chunk_text,
    doc_metadata_json,
    content='document_chunks',
    content_rowid='chunk_id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS trg_chunks_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO rag_chunks_fts(rowid, file_name, heading_context, chunk_text, doc_metadata_json)
    VALUES (new.chunk_id, new.file_name, new.heading_context, new.chunk_text, new.doc_metadata_json);
END;
CREATE TRIGGER IF NOT EXISTS trg_chunks_ad AFTER DELETE ON document_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, file_name, heading_context, chunk_text, doc_metadata_json)
    VALUES ('delete', old.chunk_id, old.file_name, old.heading_context, old.chunk_text, old.doc_metadata_json);
END;
CREATE TRIGGER IF NOT EXISTS trg_chunks_au AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, file_name, heading_context, chunk_text, doc_metadata_json)
    VALUES ('delete', old.chunk_id, old.file_name, old.heading_context, old.chunk_text, old.doc_metadata_json);
    INSERT INTO rag_chunks_fts(rowid, file_name, heading_context, chunk_text, doc_metadata_json)
    VALUES (new.chunk_id, new.file_name, new.heading_context, new.chunk_text, new.doc_metadata_json);
END;

CREATE TABLE IF NOT EXISTS folder_manifests (
    manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT UNIQUE NOT NULL,
    parent_path TEXT NOT NULL DEFAULT '',
    folder_name TEXT NOT NULL DEFAULT '',
    total_files INTEGER NOT NULL DEFAULT 0,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    file_types_json TEXT NOT NULL DEFAULT '{}',
    structural_summary TEXT NOT NULL DEFAULT '',
    topics_json TEXT NOT NULL DEFAULT '[]',
    backing_dev TEXT NOT NULL DEFAULT '',
    visibility_tier TEXT NOT NULL DEFAULT 'public_share',
    owner_username TEXT NOT NULL DEFAULT '',
    share_name TEXT NOT NULL DEFAULT '',
    allowed_users_csv TEXT NOT NULL DEFAULT '*',
    indexed_at REAL NOT NULL,
    last_verified_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_manifest_parent ON folder_manifests(parent_path);
CREATE INDEX IF NOT EXISTS idx_manifest_rbac ON folder_manifests(visibility_tier, owner_username, share_name);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_manifests_fts USING fts5(
    folder_name,
    folder_path,
    structural_summary,
    topics_json,
    content='folder_manifests',
    content_rowid='manifest_id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS trg_manifests_ai AFTER INSERT ON folder_manifests BEGIN
    INSERT INTO rag_manifests_fts(rowid, folder_name, folder_path, structural_summary, topics_json)
    VALUES (new.manifest_id, new.folder_name, new.folder_path, new.structural_summary, new.topics_json);
END;
CREATE TRIGGER IF NOT EXISTS trg_manifests_ad AFTER DELETE ON folder_manifests BEGIN
    INSERT INTO rag_manifests_fts(rag_manifests_fts, rowid, folder_name, folder_path, structural_summary, topics_json)
    VALUES ('delete', old.manifest_id, old.folder_name, old.folder_path, old.structural_summary, old.topics_json);
END;
CREATE TRIGGER IF NOT EXISTS trg_manifests_au AFTER UPDATE ON folder_manifests BEGIN
    INSERT INTO rag_manifests_fts(rag_manifests_fts, rowid, folder_name, folder_path, structural_summary, topics_json)
    VALUES ('delete', old.manifest_id, old.folder_name, old.folder_path, old.structural_summary, old.topics_json);
    INSERT INTO rag_manifests_fts(rowid, folder_name, folder_path, structural_summary, topics_json)
    VALUES (new.manifest_id, new.folder_name, new.folder_path, new.structural_summary, new.topics_json);
END;

CREATE TABLE IF NOT EXISTS photo_assets (
    file_id INTEGER PRIMARY KEY REFERENCES indexed_files(file_id) ON DELETE CASCADE,
    file_name TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    aspect_ratio REAL NOT NULL DEFAULT 1.0,
    format TEXT NOT NULL DEFAULT 'JPEG',
    taken_at REAL,
    camera_make TEXT NOT NULL DEFAULT '',
    camera_model TEXT NOT NULL DEFAULT '',
    lens_model TEXT NOT NULL DEFAULT '',
    iso INTEGER,
    focal_length_mm REAL,
    aperture_f REAL,
    gps_lat REAL,
    gps_lon REAL,
    location_label TEXT NOT NULL DEFAULT '',
    when_where_done INTEGER NOT NULL DEFAULT 0,
    phash_hex TEXT NOT NULL DEFAULT '',
    dominant_hex TEXT NOT NULL DEFAULT '#1e293b',
    palette_json TEXT NOT NULL DEFAULT '[]',
    object_colors_json TEXT NOT NULL DEFAULT '{}',
    frame_colors_json TEXT NOT NULL DEFAULT '{}',
    object_colors_text TEXT NOT NULL DEFAULT '',
    color_hist_f32 BLOB,
    center_color_hist_f32 BLOB,
    scene_tags_json TEXT NOT NULL DEFAULT '[]',
    auto_tags_text TEXT NOT NULL DEFAULT '',
    caption_text TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    vision_embedding_f32 BLOB NOT NULL,
    thumb_webp BLOB,
    visibility_tier TEXT NOT NULL DEFAULT 'public_share',
    owner_username TEXT NOT NULL DEFAULT '',
    share_name TEXT NOT NULL DEFAULT '',
    allowed_users_csv TEXT NOT NULL DEFAULT '*'
);

CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photo_assets(taken_at DESC);
CREATE INDEX IF NOT EXISTS idx_photos_rbac ON photo_assets(visibility_tier, owner_username, share_name);
CREATE INDEX IF NOT EXISTS idx_photos_phash ON photo_assets(phash_hex);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_photos_fts USING fts5(
    file_name,
    object_colors_text,
    auto_tags_text,
    caption_text,
    camera_model,
    location_label,
    content='photo_assets',
    content_rowid='file_id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS trg_photos_ai AFTER INSERT ON photo_assets BEGIN
    INSERT INTO rag_photos_fts(rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
    VALUES (new.file_id, new.file_name, new.object_colors_text, new.auto_tags_text, new.caption_text, new.camera_model, new.location_label);
END;
CREATE TRIGGER IF NOT EXISTS trg_photos_ad AFTER DELETE ON photo_assets BEGIN
    INSERT INTO rag_photos_fts(rag_photos_fts, rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
    VALUES ('delete', old.file_id, old.file_name, old.object_colors_text, old.auto_tags_text, old.caption_text, old.camera_model, old.location_label);
END;
CREATE TRIGGER IF NOT EXISTS trg_photos_au AFTER UPDATE ON photo_assets BEGIN
    INSERT INTO rag_photos_fts(rag_photos_fts, rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
    VALUES ('delete', old.file_id, old.file_name, old.object_colors_text, old.auto_tags_text, old.caption_text, old.camera_model, old.location_label);
    INSERT INTO rag_photos_fts(rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
    VALUES (new.file_id, new.file_name, new.object_colors_text, new.auto_tags_text, new.caption_text, new.camera_model, new.location_label);
END;

CREATE TABLE IF NOT EXISTS rag_deferred_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_path TEXT UNIQUE NOT NULL,
    backing_dev TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT 'disk_standby',
    queued_at REAL NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deferred_dev ON rag_deferred_queue(backing_dev, priority DESC);
"""

TAGS = (
    "CREATE TABLE IF NOT EXISTS doc_tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (file_id, tag))",
    "CREATE INDEX IF NOT EXISTS idx_doc_tags_tag ON doc_tags(tag, file_id)",
    # every file that was tagged, even with no tag, so the backfill reads each file once
    "CREATE TABLE IF NOT EXISTS doc_tags_done (file_id INTEGER PRIMARY KEY)",
)

CJK_TABLE = "rag_chunks_cjk"
CJK = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {CJK_TABLE} USING fts5(grams, content='', contentless_delete=1, tokenize='unicode61')",
    f"CREATE TRIGGER IF NOT EXISTS trg_chunks_cjk_ad AFTER DELETE ON document_chunks BEGIN "
    f"DELETE FROM {CJK_TABLE} WHERE rowid = old.chunk_id; END",
    f"CREATE TRIGGER IF NOT EXISTS trg_chunks_cjk_au AFTER UPDATE OF chunk_text ON document_chunks BEGIN "
    f"DELETE FROM {CJK_TABLE} WHERE rowid = old.chunk_id; END",
)

PHOTO_SEMANTIC = """
CREATE TABLE IF NOT EXISTS photo_semantic (
    file_id INTEGER PRIMARY KEY REFERENCES indexed_files(file_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    vec BLOB NOT NULL
);
"""

VISION = """
CREATE TABLE IF NOT EXISTS photo_vision (
    content_key TEXT PRIMARY KEY,
    model TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'done',
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pdf_ocr (
    path TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    pages INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'done',
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (path, mtime_ns)
);
"""

REEMBED_STAGING = (
    "CREATE TABLE IF NOT EXISTS reembed_staging ("
    "chunk_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL)"
)


def vec0(table: str, dim: int) -> str:
    """The sqlite-vec index for one embedding size, with int8 vectors (AI-18)."""
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding int8[{int(dim)}], file_id INTEGER, visibility_tier TEXT)"
    )
