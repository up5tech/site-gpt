import { Alert, Card, Typography } from 'antd';
import { Chat } from '../components/Chat';

const { Title, Text, Paragraph } = Typography;

export function Playground() {
  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={2}>Playground</Title>
        <Text type='secondary'>
          Test your bot before embedding it on a site. Pick a website, ask
          questions, and review the cited sources and feedback the same way
          your visitors will see them.
        </Text>
      </div>

      <Alert
        message='This is a private testing environment'
        description='Messages sent here are stored like any other chat. Use it to validate answers and knowledge coverage, not as the public widget.'
        type='info'
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Card variant='borderless' className='premium-card'>
        <Chat />
      </Card>

      <Paragraph type='secondary' style={{ marginTop: 16, fontSize: 12 }}>
        Tip: low-quality or "I don&apos;t know" answers usually mean the source
        page hasn&apos;t been ingested yet — go to the website&apos;s detail page
        and run ingest.
      </Paragraph>
    </div>
  );
}
