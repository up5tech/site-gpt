import { Button, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useDocumentTitle } from '../utils/useDocumentTitle';

const { Title, Paragraph, Text } = Typography;

const CAPABILITIES = [
  {
    title: 'Train it on your own content',
    body: 'Crawl a website or sitemap, upload PDF, Word, PowerPoint, text and Markdown files, or import Google Drive, YouTube captions and Notion pages and databases.',
  },
  {
    title: 'Answers from your knowledge base',
    body: 'Each reply is retrieved from the content you ingested for that website, and the assistant says it does not know instead of inventing an answer when nothing relevant is found.',
  },
  {
    title: 'Embeddable on any site',
    body: 'One script tag adds the chat bubble to your site. Every website also gets a hosted chat page, so you can share a direct link without touching your own markup.',
  },
  {
    title: 'Human handoff when it matters',
    body: 'A visitor can ask for a person. With the live-agent inbox enabled, your team claims the conversation, replies from the console and the widget switches over.',
  },
  {
    title: 'Analytics and a weekly digest',
    body: 'Track conversation volume, engagement and the questions people actually ask, export the window as CSV and optionally receive the summary by email.',
  },
  {
    title: 'An API for your own systems',
    body: 'Versioned API keys with scopes let your backend ingest content or ask questions server-to-server, separate from the admin console login.',
  },
];

const STEPS = [
  {
    title: 'Add a website',
    body: 'Create a website in the console and point it at a sitemap, or upload the documents and sources you already have.',
  },
  {
    title: 'Let it ingest',
    body: 'The worker extracts text, chunks it and stores an embedding per chunk, so answers are grounded in what you trained it on.',
  },
  {
    title: 'Embed and tune',
    body: 'Paste the snippet into your site, set the assistant greeting and language, and watch the conversations your customers have.',
  },
];

const FAQ = [
  {
    q: 'What content can I train it on?',
    a: 'A website crawled from its sitemap, uploaded PDF/DOCX/PPTX/TXT/Markdown files, Google Drive documents, YouTube captions and Notion pages or databases. The supported sources are the ones listed in the console upload form.',
  },
  {
    q: 'Where does the content live?',
    a: 'Answers are scoped to the website that was asked. Content, conversations and retention are managed per company in the admin console, and a retention policy can delete old conversations automatically.',
  },
  {
    q: 'Can a human take over a conversation?',
    a: 'Yes. The live-agent inbox is a per-company switch. When it is enabled a visitor can request a person and an agent can claim, reply to and close the conversation from the console.',
  },
  {
    q: 'Who can access the admin console?',
    a: 'Accounts created through the registration form belong to a company. Within that company, users have roles that gate settings, billing-relevant limits, API keys and the live inbox.',
  },
  {
    q: 'Is there an API?',
    a: 'Yes. Company admins can mint scoped API keys in Settings, and the versioned API covers ingest and chat without exposing the admin login.',
  },
];

export function Landing() {
  useDocumentTitle(
    'Site GPT — AI support chatbot trained on your own content',
  );
  const { isAuthenticated } = useAuth();

  return (
    <div>
      <section className='marketing-hero' aria-labelledby='hero-title'>
        <div>
          <span className='marketing-eyebrow'>AI support assistant</span>
          <Title level={1} id='hero-title'>
            A support chatbot that answers from your own content
          </Title>
          <Paragraph className='lead'>
            Train Site GPT on your website, documents and knowledge sources, then
            embed it on your site. It answers customer questions from what you
            published — and hands the conversation to your team when a person is
            needed.
          </Paragraph>
          <div className='marketing-cta-row'>
            {isAuthenticated ? (
              <Link to='/app'>
                <Button type='primary' size='large'>
                  Go to the console
                </Button>
              </Link>
            ) : (
              <>
                <Link to='/register'>
                  <Button type='primary' size='large'>
                    Create an account
                  </Button>
                </Link>
                <Link to='/pricing'>
                  <Button size='large'>See plans</Button>
                </Link>
              </>
            )}
          </div>
        </div>
        <div className='marketing-hero-panel'>
          <ul>
            {[
              'Website crawl from a sitemap',
              'PDF, Word, PowerPoint, text and Markdown uploads',
              'Google Drive, YouTube and Notion imports',
              'Embeddable widget plus a hosted chat page',
              'Human handoff and a live-agent inbox',
              'Scoped API keys for your own backend',
            ].map((item) => (
              <li key={item}>
                <span className='marketing-check' aria-hidden='true'>
                  ✓
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className='marketing-section' aria-labelledby='capabilities-title'>
        <div className='marketing-section-heading'>
          <Title level={2} id='capabilities-title'>
            Everything a support bot needs
          </Title>
          <Paragraph>
            The same console trains the assistant, embeds it and shows you what
            customers are asking.
          </Paragraph>
        </div>
        <div className='marketing-grid'>
          {CAPABILITIES.map((item) => (
            <article className='marketing-card' key={item.title}>
              <Title level={3}>{item.title}</Title>
              <Paragraph>{item.body}</Paragraph>
            </article>
          ))}
        </div>
      </section>

      <section className='marketing-section' aria-labelledby='how-title'>
        <div className='marketing-section-heading'>
          <Title level={2} id='how-title'>
            How it works
          </Title>
          <Paragraph>Three steps from your content to a live assistant.</Paragraph>
        </div>
        <ol className='marketing-steps'>
          {STEPS.map((step) => (
            <li key={step.title}>
              <Title level={3}>{step.title}</Title>
              <Paragraph>{step.body}</Paragraph>
            </li>
          ))}
        </ol>
      </section>

      <section
        className='marketing-section'
        id='faq'
        aria-labelledby='faq-title'
      >
        <div className='marketing-section-heading'>
          <Title level={2} id='faq-title'>
            Frequently asked questions
          </Title>
        </div>
        <div className='marketing-faq'>
          {FAQ.map((item) => (
            <details key={item.q}>
              <summary>{item.q}</summary>
              <Paragraph>{item.a}</Paragraph>
            </details>
          ))}
        </div>
      </section>

      <section className='marketing-cta-row marketing-section compact'>
        {isAuthenticated ? (
          <Link to='/app'>
            <Button type='primary' size='large'>
              Go to the console
            </Button>
          </Link>
        ) : (
          <>
            <Link to='/register'>
              <Button type='primary' size='large'>
                Create an account
              </Button>
            </Link>
            <Link to='/pricing'>
              <Button size='large'>See plans</Button>
            </Link>
          </>
        )}
      </section>

      <div className='marketing-banner'>
        <Text type='secondary'>
          Plans and pricing are published once approved. Prices are shown on the{' '}
          <Link to='/pricing'>pricing page</Link> and are the only source of
          billing information.
        </Text>
      </div>
    </div>
  );
}
