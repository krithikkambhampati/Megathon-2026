// React + htm bindings shared by every module (React is loaded from /vendor as a UMD global).
export const React = window.React;
export const ReactDOM = window.ReactDOM;
export const html = window.htm.bind(React.createElement);
export const { useState, useEffect, useMemo, useRef, useCallback, useSyncExternalStore, Fragment } = React;
