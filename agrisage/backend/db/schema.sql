-- AgriSage: 질병-농약 매핑 + 사후관리 케이스 스키마

CREATE TABLE IF NOT EXISTS diseases (
    class_name TEXT PRIMARY KEY,
    crop TEXT NOT NULL,
    crop_en TEXT,
    disease_name TEXT NOT NULL,
    pathogen_type TEXT
);

CREATE TABLE IF NOT EXISTS healthy_labels (
    class_name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    class_name TEXT NOT NULL REFERENCES diseases(class_name) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    active_ingredient TEXT,
    phi_days INTEGER NOT NULL,
    organic_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_products_class_name ON products(class_name);

CREATE TABLE IF NOT EXISTS followup_cases (
    case_id TEXT PRIMARY KEY,
    crop TEXT NOT NULL,
    original_class TEXT NOT NULL,
    created_at DATE NOT NULL,
    followup_due DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_followup',
    followup_verdict TEXT,
    followup_message TEXT,
    followup_prediction JSONB
);
