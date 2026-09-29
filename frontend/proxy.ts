import { NextResponse, type NextRequest } from "next/server";

// Optimistic check only: no refresh cookie → go to sign-in. Authorisation is enforced by the API.
export function proxy(request: NextRequest) {
  if (!request.cookies.has("sutra_rt")) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico).*)"],
};
