import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="page">
      <section className="page-state page-state--empty">
        <span className="page-state__symbol page-state__symbol--empty" aria-hidden="true">
          404
        </span>
        <div>
          <h1>Page not found</h1>
          <p>The page you requested is not part of this local monitor.</p>
          <Link className="button button--secondary" to="/">
            Return to overview
          </Link>
        </div>
      </section>
    </div>
  );
}
