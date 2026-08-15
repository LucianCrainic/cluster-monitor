import type { Node } from "../types/api";

export function maxGpuCount(node: Node): number {
  let total = 0;
  for (const resource of node.generic_resources ?? []) {
    const match = resource.match(/(?:^|,)gpu(?::[^:,()]+)?:(\d+)/i);
    if (match) total += Number(match[1]);
  }
  if (total > 0) return total;
  for (const label of node.gpu_resources ?? []) {
    const match = label.match(/(?:x|:)(\d+)\b/i);
    if (match) total += Number(match[1]);
  }
  return total;
}
