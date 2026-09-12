// sw.js — Minimal service worker for PWA install-to-homescreen.
//
// This file exists SOLELY to satisfy Chrome's requirement that a service
// worker be registered before `display: standalone` works. It does NOT
// implement offline support — the app still needs a network connection.
//
// What it does:
//   1. On install: pre-caches the app shell (HTML, CSS, JS, icons) so the
//      browser knows this is a "real" PWA.
//   2. On fetch: network-first for everything (no offline fallback).
//      A failed network request still fails — we just cache the shell
//      assets to satisfy Chrome's installability check.
//
// Cache version: bump this when you change the cache list to force a
// fresh cache. The old cache is deleted in the activate handler.
// v2: added /manifest.json (the new root-level manifest route).
const CACHE_VERSION = 2;
const CACHE_NAME = `portfoliarr-v${CACHE_VERSION}`;

// App shell assets to pre-cache on install. These are the files that
// make up the skeleton of every page — the same ones the browser would
// fetch on a normal visit anyway. We just tell the SW to hold a copy.
const SHELL_ASSETS = [
    '/',
    '/static/style.css',
    '/static/js/common.js',
    '/static/js/main.js',
    '/static/js/stock.js',
    '/static/favicon.png',
    '/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png',
];

// Install: pre-cache the app shell. `skipWaiting()` activates immediately
// so the SW controls the page on first load (not the next visit).
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
    );
    self.skipWaiting();
});

// Activate: delete old caches when a new SW version takes over.
// Without this, old versions' caches would stick around forever.
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

// Fetch: network-first. We go to the network first; if it succeeds, we
// cache the response (for the shell assets) and return it. If the network
// fails, we try the cache. If both fail, the request fails — no offline
// page, no fake data. This keeps the behavior identical to a non-PWA:
// the app needs a connection, it just looks native when installed.
self.addEventListener('fetch', (event) => {
    // Only cache GET requests (POST, PUT, etc. should never be cached).
    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Only cache successful responses from our own origin.
                // Cross-origin requests (CDNs, Yahoo Finance) are not cached.
                if (
                    response.ok &&
                    event.request.url.startsWith(self.location.origin)
                ) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed — try the cache. If it's not cached either,
                // this rejects and the browser shows its normal error page.
                return caches.match(event.request);
            })
    );
});
