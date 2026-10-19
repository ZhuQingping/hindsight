import React, {type ReactNode} from 'react';
import Layout from '@theme/Layout';
import type {Props} from '@theme/BlogLayout';
import styles from './styles.module.css';

// Blog posts get a sticky contents list + Cloud CTA on the left and a
// "Back to top" button on the right. List pages (no toc) keep the centred column.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export default function BlogLayout({sidebar: _sidebar, toc, children, ...layoutProps}: Props): ReactNode {
  if (!toc) {
    return (
      <Layout {...layoutProps}>
        <div className="container margin-vert--lg">
          <div className="row">
            <main className="col col--8 col--offset-2">{children}</main>
          </div>
        </div>
      </Layout>
    );
  }
  return (
    <Layout {...layoutProps}>
      <div className="container margin-vert--lg">
        <div className="row">
          <aside className={`col col--3 ${styles.rail}`}>
            <div className={styles.sticky}>
              <div className={styles.railTitle}>On this page</div>
              {toc}
              <div className={styles.cta}>
                <div className={styles.ctaTitle}>Deploy ContextBase</div>
                <p>Long-term memory for your agents on your own infrastructure.</p>
                <a className="button button--primary button--sm" href="/developer/installation" target="_blank" rel="noopener noreferrer">
                  Get started →
                </a>
              </div>
            </div>
          </aside>
          <main className="col col--7">{children}</main>
          <aside className={`col col--2 ${styles.rail}`}>
            <div className={styles.stickyBottom}>
              <button type="button" className={styles.backToTop} onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}>
                Back to top ↑
              </button>
            </div>
          </aside>
        </div>
      </div>
    </Layout>
  );
}
