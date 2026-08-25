<?php
// PHP half of the data-directory resolver. Mirrors src/paths.py — keep the two
// in sync; both must honour DB_DATA_DIR or a test that overrides it in one
// language will still write to real data through the other.
//
// chat.php and webhook.php spawn the Python handler, so they also pass
// DB_DATA_DIR down to it (see db_run_agent in agent_client.php).

/**
 * Absolute path to the runtime data directory. DB_DATA_DIR overrides the
 * default <repo>/data, so tests can be pointed at a throwaway directory and
 * physically cannot touch live sessions, health logs, or dialectics.
 */
function db_data_dir()
{
    $override = getenv('DB_DATA_DIR');
    if ($override === false || trim($override) === '') {
        // $_SERVER carries it under some SAPIs where getenv() does not.
        $override = isset($_SERVER['DB_DATA_DIR']) ? $_SERVER['DB_DATA_DIR'] : '';
    }
    $override = trim((string)$override);
    if ($override !== '') {
        return rtrim($override, '/');
    }
    return dirname(__FILE__) . '/../data';
}

/** Path to something inside the data directory. */
function db_data_path($rel)
{
    return db_data_dir() . '/' . ltrim($rel, '/');
}
