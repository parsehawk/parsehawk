import "@testing-library/jest-dom/vitest";

function createStorageMock(): Storage {
  const values = new Map<string, string>();

  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key: string) {
      return values.get(key) ?? null;
    },
    key(index: number) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string) {
      values.delete(key);
    },
    setItem(key: string, value: string) {
      values.set(key, value);
    }
  };
}

function hasUsableLocalStorage() {
  try {
    return typeof window.localStorage !== "undefined";
  } catch {
    return false;
  }
}

if (!hasUsableLocalStorage()) {
  const storage = createStorageMock();
  Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;
globalThis.scrollTo = () => {};
Element.prototype.scrollTo = () => {};
document.execCommand = () => true;
