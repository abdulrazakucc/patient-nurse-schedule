/*
 * Opening the sealed copy of NeoStay's data published on GitHub Pages.
 *
 * scripts/build_pages_site.py encrypts the data bundles under one random
 * AES-256-GCM key, and wraps that key once per account with a key derived from
 * the account's password: PBKDF2-HMAC-SHA256, with the salt and iteration count
 * from the users file. Here the browser repeats that derivation from what the
 * reader types. The right credentials unwrap the key and decrypt the data;
 * anything else fails the authentication tag and reveals nothing. No password
 * or email address is sent anywhere.
 */
(function (root) {
  "use strict";

  const encoder = new TextEncoder();
  const MAGIC = "NEOS1";
  const CONTEXT = "neostay-sealed-v1";
  const WRONG = "Email or password is incorrect.";

  /* kind: "auth" (credentials or an outdated sign-in), "load" (network or
     format), or "browser" (missing capabilities). */
  class SealedError extends Error {
    constructor(message, kind) {
      super(message);
      this.kind = kind;
    }
  }

  function toB64(buffer) {
    const bytes = new Uint8Array(buffer);
    let text = "";
    for (let i = 0; i < bytes.length; i++) text += String.fromCharCode(bytes[i]);
    return btoa(text);
  }

  const fromB64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

  function supported() {
    return Boolean(
      root.isSecureContext && root.crypto && root.crypto.subtle && typeof root.DecompressionStream !== "undefined"
    );
  }

  async function sha256Hex(text) {
    const digest = await root.crypto.subtle.digest("SHA-256", encoder.encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function fetchOk(fetcher, path) {
    let response;
    try {
      response = await fetcher(path, { cache: "no-store" });
    } catch {
      throw new SealedError("NeoStay's protected data could not be loaded. Check your connection and try again.", "load");
    }
    if (!response.ok) throw new SealedError("NeoStay's protected data could not be loaded.", "load");
    return response;
  }

  /** The data key, if these credentials belong to an account sealed into this copy. */
  async function unlock(email, password, fetcher = (...args) => root.fetch(...args)) {
    if (!supported()) {
      throw new SealedError(
        "This browser cannot open NeoStay's protected data. Use a current version of Edge, Chrome, Firefox or Safari.",
        "browser"
      );
    }
    const keys = await (await fetchOk(fetcher, "keys.json")).json();
    const id = await sha256Hex(`${CONTEXT}:${email.trim().toLowerCase()}`);
    const entry = keys.users.find((user) => user.id === id);
    const material = await root.crypto.subtle.importKey(
      "raw", encoder.encode(password.normalize("NFKC")), "PBKDF2", false, ["deriveBits"]
    );
    // Derive even for an unknown email, so both kinds of failure take as long.
    const bits = await root.crypto.subtle.deriveBits(
      {
        name: "PBKDF2",
        hash: "SHA-256",
        salt: entry ? fromB64(entry.salt) : new Uint8Array(16),
        iterations: entry ? entry.iterations : keys.iterations,
      },
      material,
      256
    );
    if (!entry) throw new SealedError(WRONG, "auth");
    const wrappingKey = await root.crypto.subtle.importKey("raw", bits, "AES-GCM", false, ["decrypt"]);
    try {
      return await root.crypto.subtle.decrypt(
        { name: "AES-GCM", iv: fromB64(entry.nonce), additionalData: encoder.encode(id) },
        wrappingKey,
        fromB64(entry.wrapped)
      );
    } catch {
      throw new SealedError(WRONG, "auth");
    }
  }

  /** Decrypt and decompress the data bundle with an unwrapped key. */
  async function openBundle(rawKey, fetcher = (...args) => root.fetch(...args)) {
    const bytes = new Uint8Array(await (await fetchOk(fetcher, "data.sealed")).arrayBuffer());
    if (new TextDecoder().decode(bytes.slice(0, MAGIC.length)) !== MAGIC) {
      throw new SealedError("NeoStay's protected data is in an unexpected format.", "load");
    }
    const key = await root.crypto.subtle.importKey("raw", rawKey, "AES-GCM", false, ["decrypt"]);
    let plain;
    try {
      plain = await root.crypto.subtle.decrypt(
        { name: "AES-GCM", iv: bytes.slice(MAGIC.length, MAGIC.length + 12), additionalData: encoder.encode(CONTEXT) },
        key,
        bytes.slice(MAGIC.length + 12)
      );
    } catch {
      // The copy was republished with a new key since this browser signed in.
      throw new SealedError("NeoStay has been updated since you signed in. Please sign in again.", "auth");
    }
    const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }

  root.NeoSealed = { unlock, openBundle, toB64, fromB64, supported, SealedError, MAGIC, CONTEXT };
})(typeof window !== "undefined" ? window : globalThis);
