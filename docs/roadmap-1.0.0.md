# bantamkit 1.0.0 roadmap

Author product behavior once in TypeScript and ship it to two targets. A single build entry point type-checks the canonical source, emits JavaScript and TypeScript declarations for `bantamkit-mcp` on npm, and uses a Rust compiler to generate Python source for the `bantamkit` wheel. Rust is a build-time tool. Each installed package runs on its own runtime.

## Architecture

| Layer | Responsibility |
| --- | --- |
| Domain | Canonical TypeScript for product rules, data transformations, and validation decisions. |
| Application | Canonical TypeScript for use cases and interfaces to I/O. Shared code depends on those interfaces. |
| Runtime adapters | Thin Node and Python implementations for filesystem, subprocesses, clocks, and MCP SDK integration where needed. Adapters translate platform values and errors at the boundary. |
| Package entry points | Preserve existing public imports, MCP tools, and CLI commands. Inventory Python-only public behavior and migrate it into the canonical TypeScript source, with target-specific exposure where required. |

Keep shared assets canonical and package them for both targets. Treat generated Python modules as build output. Fix product behavior in TypeScript and fix translation defects in the compiler. Check dependency direction and regenerate release artifacts from a clean checkout in CI.

## Rollout

| Phase | Deliverable | Exit criteria |
| --- | --- | --- |
| 0. Baseline and inventory | Map modules, dependencies, public contracts, Python-only surfaces, platform APIs, and approved runtime differences. Capture existing conformance, package size, build time, startup time, and supported OS/runtime matrix. | Every public surface and stored format has an owner, a migration group, and a compatibility check. Record baselines before setting release budgets. |
| 1. Compiler pilot — `workplan` | Generate the Python planner from TypeScript. Document the supported TypeScript subset. Reject unsupported constructs at build time with source locations. | Node and generated Python pass the same expected outputs, including the 21 existing real graphs and edge cases. Compare generated Python against the legacy implementation before switching. |
| 2. Compiler validation — `codec` | Migrate the fact-file codec to test reuse of compiler rules across a second kind of workload. Explicitly cover observable string, ordering, and serialization semantics. | Both targets produce identical bytes where required and read files written by previous releases. Update the remaining rollout estimates using actual pilot results. |
| 3. Migrate by dependency group | Move shared logic in dependency order, add the necessary adapters, and migrate Python-only behavior. Land each group with contract tests and remove the superseded Python implementation and duplicate tests once equivalent coverage passes. | Every product behavior has one canonical source. Each remaining handwritten runtime-specific module has a documented platform responsibility. Existing public contracts pass on both targets, including explicitly documented target-specific behavior. |
| 4. Harden and optimize packaging | Exercise production builds, measure minification, and add release security checks against the actual npm tarball and Python wheel. | Both artifacts meet the size and performance budgets agreed after baselining, pass package-content checks, and install and run on the supported matrix. |
| 5. Release candidate and 1.0.0 | Build both packages from the same commit. Exercise clean installs and upgrades with representative existing stores. Publish matching 1.0.0 releases after the release candidate passes. | Public imports and CLI entry points work, MCP behavior and persisted data meet the compatibility baseline, and the release candidate validates recovery with the prior supported package versions and preserved store data. |

### Test ownership and sizing

Extend the [existing conformance harness](conformance.md). Author shared test inputs and expected outcomes once and run them against both targets. Keep explicit expected values for behavior where two targets could regress together, plus target-specific tests for adapters, packaging, CLI behavior, and documented platform differences. Preserve existing coverage when retiring duplicated tests.

Track pilot effort for source changes, new and reused compiler rules, adapters, and contract coverage. Record the number of duplicated test cases retired. After `codec`, estimate the remaining work by dependency group and give a range that reflects unresolved compiler semantics and platform integrations. Use that inventory to decide migration order and release scope.

### Minification and security

- **npm:** Minify emitted JavaScript with a pinned tool. Preserve entry points, exported names, declarations, and observable behavior. Compare the packed tarball before and after minification and run package smoke tests against the production output.
- **PyPI:** Ship readable generated Python in the compressed wheel. Measure size and trim unused package content while keeping assets, metadata, and debugging information needed by users. Evaluate further Python minification only if measurements show a material gain and the wheel passes the same compatibility checks.
- **Build and release:** Pin build dependencies and check for known vulnerable dependencies, secrets, and unexpected files before publishing. Check packaged source maps and debug artifacts against the intended distribution policy. Record artifact hashes and the source commit used for each build.
- **Runtime boundaries:** Validate MCP inputs and file paths at their boundaries. Test rejection of paths outside authorized roots where access is scoped, safe subprocess argument handling, and redaction of sensitive values in logs and errors.

### Optional small functions

Extract small pure functions when they isolate a rule, make behavior easier to test, or let both targets share the same implementation. Keep related behavior together when splitting would only add indirection. This is optional for 1.0.0.
