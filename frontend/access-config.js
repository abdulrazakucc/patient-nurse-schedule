/* How this copy of NeoStay signs people in.
 *
 *   "server" -- a NeoStay server checks email and password (a hospital server,
 *               or `make run` on a laptop). The data loads only after sign-in.
 *   "sealed" -- the GitHub Pages copy. The data is published encrypted and opens
 *               in the browser with a registered account's password.
 *   "closed" -- a GitHub Pages copy published before any account exists: the
 *               landing page only, with no sign-in form, application or data.
 * scripts/build_pages_site.py writes the "sealed" and "closed" versions.
 */
window.NEOSTAY_ACCESS = { mode: "server" };
