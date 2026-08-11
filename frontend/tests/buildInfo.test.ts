import { describe, expect, it } from "vitest";

import {
  buildsDiffer,
  feedbackBuildContext,
  type BuildInfo,
} from "../src/lib/buildInfo";

const frontend: BuildInfo = {
  service: "frontend",
  release_version: "0.1.0",
  build_sha: "aaaaaaa1111111",
  build_id: "0.1.0+aaaaaaa",
  environment: "production",
};

describe("build identity", () => {
  it("detects independently deployed SHAs", () => {
    expect(buildsDiffer(frontend, { ...frontend, service: "api" })).toBe(false);
    expect(
      buildsDiffer(frontend, { ...frontend, service: "api", build_sha: "bbbbbbb2222222" }),
    ).toBe(true);
    expect(buildsDiffer(frontend, undefined)).toBe(false);
  });

  it("keeps feedback useful when the API version request is unavailable", () => {
    expect(feedbackBuildContext(frontend.build_id, undefined)).toBe("0.1.0+aaaaaaa");
    expect(
      feedbackBuildContext(frontend.build_id, {
        ...frontend,
        service: "api",
        build_sha: "bbbbbbb2222222",
        build_id: "0.1.0+bbbbbbb",
      }),
    ).toBe("frontend 0.1.0+aaaaaaa · api 0.1.0+bbbbbbb");
  });
});
