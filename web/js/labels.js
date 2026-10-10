// Plain-English labels from /v1/labels (greenhome/labels.py), loaded once at start-up.
let L = { enums: {}, component: {}, flag: {}, issue: {}, reason: {}, field: {}, yes_no: {}, not_sure: "Not sure" };
export function setLabels(data) { L = data; }
export const NOT_SURE = () => L.not_sure;
export const label = (enumName, value) => (value === null || value === undefined) ? L.not_sure : ((L.enums[enumName] || {})[value] ?? value);
export const options = (enumName) => Object.entries(L.enums[enumName] || {}).map(([value, text]) => ({ value, label: text }));
export const issueText = (code) => L.issue[code] ?? code;
export const reasonText = (code) => L.reason[code] ?? code;
export const flagText = (code) => L.flag[code] ?? code;
export const componentText = (key) => L.component[key] ?? key;
export const fieldText = (key) => L.field[key] ?? key;
export const yesNo = (v) => (v === null || v === undefined) ? L.not_sure : (L.yes_no[v] ?? v);
