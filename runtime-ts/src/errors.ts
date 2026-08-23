/**
 * The error base the Python runtime exposes from `bantamkit.client` as `BantamError`.
 *
 * It lives in its own module here rather than in a port of `client.py`, because the
 * prep probe measured that `client.py` contributes exactly two things to the MCP
 * surface — this base class and the `Tool` dataclass — and nothing else in that file
 * is reachable from the seven tools.
 */
export class BantamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}
