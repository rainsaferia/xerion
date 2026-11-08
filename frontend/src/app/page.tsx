import { api, type ReadyResponse } from "@/lib/api-client";

async function loadStatus(): Promise<ReadyResponse | null> {
  try {
    return await api.ready();
  } catch {
    return null;
  }
}

export default async function Home() {
  const status = await loadStatus();

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-semibold">Project Intelligence Platform</h1>
      <p className="mt-2 text-sm text-zinc-600">
        Foundation (PI-001). No project data is loaded yet.
      </p>
      <section className="mt-6" aria-label="System status">
        <h2 className="text-lg font-medium">System status</h2>
        {status === null ? (
          <p role="status" className="mt-2 text-red-700">
            Backend unreachable.
          </p>
        ) : (
          <ul className="mt-2 space-y-1" role="status">
            <li>API: {status.status}</li>
            {Object.entries(status.checks).map(([name, state]) => (
              <li key={name}>
                {name}: {state}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
