const ACCOUNTS_KEY = "citypulse.accounts.v1";
const SESSION_KEY = "citypulse.session.v1";

function readAccounts() {
  try {
    const value = JSON.parse(localStorage.getItem(ACCOUNTS_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function bytesToHex(bytes) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function passwordHash(password, salt) {
  const encoder = new TextEncoder();
  const key = await globalThis.crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await globalThis.crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: 120000 }, key, 256);
  return bytesToHex(bits);
}

export async function registerAccount(name, password) {
  const normalizedName = name.trim().toLowerCase();
  const accounts = readAccounts();
  if (accounts[normalizedName]) throw new Error("An account with this name already exists.");
  if (!globalThis.crypto?.subtle) throw new Error("Secure password storage is unavailable in this browser.");

  const salt = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const saltHex = bytesToHex(salt);
  const hash = await passwordHash(password, salt);
  accounts[normalizedName] = { name: name.trim(), salt: saltHex, hash };
  localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
  sessionStorage.setItem(SESSION_KEY, normalizedName);
  return { name: name.trim() };
}

export async function loginAccount(name, password) {
  const normalizedName = name.trim().toLowerCase();
  const account = readAccounts()[normalizedName];
  if (!account || !globalThis.crypto?.subtle) throw new Error("Name or password is incorrect.");
  const salt = new Uint8Array(account.salt.match(/.{2}/g).map((byte) => Number.parseInt(byte, 16)));
  if ((await passwordHash(password, salt)) !== account.hash) throw new Error("Name or password is incorrect.");
  sessionStorage.setItem(SESSION_KEY, normalizedName);
  return { name: account.name };
}

export function currentUser() {
  try {
    const name = sessionStorage.getItem(SESSION_KEY);
    const account = name && readAccounts()[name];
    return account ? { name: account.name } : null;
  } catch {
    return null;
  }
}

export function logoutAccount() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch { /* storage may be disabled */ }
}
