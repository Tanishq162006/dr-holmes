export default function DisclaimerPage() {
  return (
    <div className="flex-1 max-w-3xl mx-auto w-full px-4 py-12 prose prose-slate dark:prose-invert">
      <h1 className="text-2xl font-bold">Disclaimer</h1>
      <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">Last updated: 2026-04-29</p>

      <h2 className="mt-8 text-lg font-semibold">What this is</h2>
      <p>
        Dr. Holmes is an educational research project demonstrating multi-agent
        large language model orchestration for diagnostic deliberation. It is
        a personal portfolio / learning project — nothing more.
      </p>

      <h2 className="mt-6 text-lg font-semibold">What this is NOT</h2>
      <ul className="list-disc list-inside space-y-1 text-sm">
        <li>NOT a medical device. NOT FDA-approved.</li>
        <li>NOT for clinical use. NOT a substitute for medical advice, diagnosis, or treatment.</li>
        <li>NOT an authoritative reference. AI outputs are frequently wrong.</li>
        <li>NOT affiliated with any television production, hospital, university, or pharmaceutical company.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">Data and privacy</h2>
      <p>
        Do not enter real patient data into this system. Use synthetic or fictional
        cases only. Cases you create are stored on the backend you connect to.
      </p>

      <h2 className="mt-6 text-lg font-semibold">If you are seeking medical care</h2>
      <p>
        Please consult a licensed physician. In emergencies, call your local
        emergency number.
      </p>

      <p className="mt-12 text-xs text-[hsl(var(--muted-foreground))]">
        © 2026 Dr. Holmes project. Source code at{" "}
        <a href="https://github.com/Tanishq162006/dr-holmes" className="underline">github.com/Tanishq162006/dr-holmes</a>
        {" "}· Released for educational use.
      </p>
    </div>
  );
}
