// The install snippet must never fall back to a bare /widget.js URL: without a
// ?v= token an embedded site can keep running a stale cached widget after a
// deploy. These checks import the real TypeScript helper (node strips types).
import {
  WIDGET_VERSION_PLACEHOLDER,
  buildWidgetSnippet,
  widgetVersionQuery,
} from '../frontend/src/utils/widgetSnippet.ts';

let passed = 0;
let failures = 0;

function check(name, condition, actual) {
  if (condition) {
    passed++;
    console.log(`ok - ${name}`);
    return;
  }
  failures++;
  console.error(`FAIL - ${name}\n  got: ${JSON.stringify(actual)}`);
}

const BASE = 'https://api.example.com';

// --- version known ----------------------------------------------------------
const withVersion = buildWidgetSnippet({
  websiteId: 'w1',
  apiUrl: BASE,
  version: 'f772da3f',
});

check(
  'versioned snippet carries ?v=<hash>',
  withVersion.includes(`/widget.js?v=f772da3f`),
  withVersion,
);
check('snippet sets the website id', withVersion.includes(`website_id: 'w1'`));
check('snippet sets apiUrl', withVersion.includes(`apiUrl: '${BASE}'`));

// --- version missing (HEAD failed / header absent) --------------------------
for (const [label, version] of [
  ['undefined', undefined],
  ['empty string', ''],
  ['whitespace', '   '],
]) {
  const snippet = buildWidgetSnippet({ websiteId: 'w1', apiUrl: BASE, version });
  check(
    `missing version (${label}) leaves a visible placeholder`,
    snippet.includes(`/widget.js?v=${WIDGET_VERSION_PLACEHOLDER}`),
    snippet,
  );
  check(
    `missing version (${label}) never emits a bare widget.js`,
    !/widget\.js["']/.test(snippet),
    snippet,
  );
}

check(
  'placeholder is the documented token',
  WIDGET_VERSION_PLACEHOLDER === '<WIDGET_VERSION>',
  WIDGET_VERSION_PLACEHOLDER,
);
check(
  'version query is always present',
  widgetVersionQuery('abc').startsWith('?v=') &&
    widgetVersionQuery().startsWith('?v='),
  widgetVersionQuery(),
);

// --- apiUrl handling --------------------------------------------------------
const trailing = buildWidgetSnippet({
  websiteId: 'w1',
  apiUrl: 'https://api.example.com///',
  version: 'abc',
});
check(
  'trailing slashes in apiUrl are trimmed',
  trailing.includes(`src="https://api.example.com/widget.js?v=abc"`) &&
    !trailing.includes('.com//'),
  trailing,
);

const spaced = buildWidgetSnippet({
  websiteId: 'w1',
  apiUrl: BASE,
  version: '  abc123  ',
});
check(
  'a padded version is trimmed',
  spaced.includes('/widget.js?v=abc123'),
  spaced,
);

check(
  'snippet keeps the async attribute',
  withVersion.includes('/widget.js?v=f772da3f" async></script>'),
  withVersion,
);

if (failures > 0) {
  console.error(`\n${failures} check(s) failed, ${passed} passed`);
  process.exit(1);
}
console.log(`\n${passed} checks passed`);
