CREATE TABLE circle_configuration (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  max_memberships smallint NOT NULL DEFAULT 5 CHECK (max_memberships BETWEEN 1 AND 20),
  updated_by uuid REFERENCES app_users(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO circle_configuration (singleton, max_memberships)
VALUES (true, 5);

CREATE UNIQUE INDEX circles_name_casefold_unique_idx
  ON circles (lower(name));

COMMENT ON TABLE circle_configuration IS
  'Administrator-managed active-circle limit. The single row starts at the client-approved value of five.';
