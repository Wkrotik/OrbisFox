/* Real mozStorage/persistent SQLite gate; main thread, project-owned DB only.
 * No cookie deletion, in-memory substitution, relaxed locking, or encryption
 * bypass. Exceptions must stop networking, not turn into success. */
function verifyTrustedPersistentStorage(Cc, Ci, host) {
  const value = "OrbisFox SQLite durable probe 🦊";
  const service = Cc["@mozilla.org/storage/service;1"].getService(Ci.mozIStorageService);
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  file.initWithPath("/data/orbisfox/gecko-profile/mozstorage-bringup.sqlite");
  let connection = null;
  const read = () => {
    const statement = connection.createStatement("SELECT value FROM orbisfox_probe WHERE id = 1");
    try {
      if (!statement.executeStep()) throw new Error("Persistent probe row missing");
      return statement.getUTF8String(0);
    } finally { statement.finalize(); }
  };
  host.log("Gecko real mozStorage: service acquired; persistent transaction probe entered");
  try {
    connection = service.openUnsharedDatabase(file);
    connection.executeSimpleSQL("CREATE TABLE IF NOT EXISTS orbisfox_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)");
    connection.executeSimpleSQL("BEGIN IMMEDIATE");
    connection.executeSimpleSQL("INSERT OR REPLACE INTO orbisfox_probe VALUES (1, '" + value + "')");
    connection.executeSimpleSQL("COMMIT");
    if (read() !== value) throw new Error("Committed probe value mismatch");
    connection.close(); connection = null;
    connection = service.openUnsharedDatabase(file);
    if (read() !== value) throw new Error("Reopened persistent probe value mismatch");
    connection.executeSimpleSQL("BEGIN IMMEDIATE");
    connection.executeSimpleSQL("UPDATE orbisfox_probe SET value = 'rollback sentinel' WHERE id = 1");
    connection.executeSimpleSQL("ROLLBACK");
    if (read() !== value) throw new Error("Rolled-back probe value mismatch");
    connection.close(); connection = null;
    host.log("Gecko real mozStorage: persistent create / commit / close / reopen / UTF-8 / rollback PASS");
    return true;
  } finally {
    if (connection) {
      try { connection.close(); }
      catch (error) { host.log("ERROR: mozStorage probe close failed: " + error); }
    }
  }
}
