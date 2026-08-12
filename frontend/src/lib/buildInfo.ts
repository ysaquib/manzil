import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./apiClient";

export interface BuildInfo {
  service: "api" | "frontend";
  release_version: string;
  build_sha: string;
  build_id: string;
  environment: string;
}

export const frontendBuildInfo: BuildInfo = {
  service: "frontend",
  release_version: import.meta.env.VITE_RELEASE_VERSION as string,
  build_sha: import.meta.env.VITE_BUILD_SHA as string,
  build_id: import.meta.env.VITE_APP_VERSION as string,
  environment: import.meta.env.MODE,
};

export function shortBuildSha(build: BuildInfo): string {
  return build.build_sha === "dev" ? "dev" : build.build_sha.slice(0, 7);
}

export function buildsDiffer(frontend: BuildInfo, api: BuildInfo | undefined): boolean {
  return api !== undefined && frontend.build_sha !== api.build_sha;
}

export function feedbackBuildContext(
  frontendVersion: string | null,
  api: BuildInfo | undefined,
): string | null {
  if (!frontendVersion) return api ? `api ${api.build_id}` : null;
  return api ? `frontend ${frontendVersion} · api ${api.build_id}` : frontendVersion;
}

export function useApiBuildInfo() {
  return useQuery({
    queryKey: ["build-info", "api"],
    queryFn: () => apiFetch<BuildInfo>("/v1/version"),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
}
