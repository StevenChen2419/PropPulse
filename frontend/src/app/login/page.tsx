"use client";
import { useState } from "react";
import { api } from "@/lib/api";

export default function LoginPage() {
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const submit = async () => {
    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.login(email, password);
      // Full browser navigation triggers AppInit re-run, which hydrates
      // the saved props and slip stores from the backend.
      window.location.href = "/";
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "Login failed. Check your credentials.";
      setError(message);
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">

        {/* Logo */}
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-gray-900">
            PropPulse
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Your sports research starts here
          </p>
        </div>

        <p className="text-sm text-gray-500 mb-5">
          Sign in with an account provisioned for this environment. Public research does not require sign-in.
        </p>

        {/* Login form */}
        <form onSubmit={event => { event.preventDefault(); void submit(); }} className="panel space-y-4 mb-4">
          <div>
            <label htmlFor="login-email" className="block text-xs font-medium text-gray-500 mb-1.5">
              Email
            </label>
            <input
              id="login-email" autoComplete="username" required type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-900 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-all"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-xs font-medium text-gray-500 mb-1.5">
              Password
            </label>
            <input
              id="login-password" autoComplete="current-password" required type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-900 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-50 transition-all"
              placeholder="Your password"
            />
          </div>

          {error && (
            <div role="alert" className="text-xs text-red-600 bg-red-50 border border-red-100 px-3 py-2 rounded-lg">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 text-[#ffffff] text-sm font-medium rounded-xl hover:bg-[#1b6656] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>


      </div>
    </main>
  );
}