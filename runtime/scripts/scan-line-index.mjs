/**
 * Build a reusable line-number resolver for one text representation.
 *
 * Keeping newline positions once and answering lookups with a binary search
 * avoids repeatedly walking the text prefix for every scanner finding.
 */
export function createLineResolver(text) {
  const lineStarts = [0];
  let newline = text.indexOf('\n');
  while (newline >= 0) {
    lineStarts.push(newline + 1);
    newline = text.indexOf('\n', newline + 1);
  }
  return (offset) => {
    let low = 0;
    let high = lineStarts.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (lineStarts[middle] <= offset) low = middle + 1;
      else high = middle;
    }
    return low;
  };
}
