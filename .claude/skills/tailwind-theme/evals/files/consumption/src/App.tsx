export function App() {
  return (
    <main className="grid gap-4 p-4 font-sans">
      <label className="grid gap-2">
        案件名称
        <input className="h-10 rounded-md border px-4 shadow-sm" />
      </label>
      <button className="h-10 rounded-md border px-4 shadow-sm">保存</button>
    </main>
  );
}
