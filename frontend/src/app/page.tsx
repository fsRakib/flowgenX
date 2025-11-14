import ApiTester from "@/components/ApiTester";

export default function Home() {
  return (
    <div className="min-h-screen bg-linear-to-br from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900">
      <div className="container mx-auto py-8 px-4">
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-bold bg-linear-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent mb-2">
            FlowGenX API Tester
          </h1>
          <p className="text-slate-600 dark:text-slate-400">
            Test Zendesk webhook APIs with a modern interface
          </p>
        </div>
        <ApiTester />
      </div>
    </div>
  );
}
