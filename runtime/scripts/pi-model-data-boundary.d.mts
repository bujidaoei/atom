export interface PiModelDataManifest {
  schemaVersion: 3;
  generatedAt: string;
  structureHash: string;
  files: Record<string, string>;
}

export interface PiModelDataBoundaryOptions {
  cacheRoot: string;
  officialRoot?: string;
  verifyIntegrity?: boolean;
}

export function verifyPiModelDataCache(options: PiModelDataBoundaryOptions): Promise<{
  manifest: PiModelDataManifest;
  providers: string[];
  endpoints: string[];
  fileCount: number;
}>;
