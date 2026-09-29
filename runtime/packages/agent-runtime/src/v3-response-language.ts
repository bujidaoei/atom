import type { V3SendMessage } from '../../product-contracts/src/v3.ts';

function explicitV3ResponseLanguage(prompt: string): V3SendMessage['responseLanguage'] {
  const englishRequested =
    /(?:请|仅|只|必须|务必|用|使用|以)[^。\n]{0,12}(?:英文|英语)|(?:英文|英语)[^。\n]{0,8}(?:回答|回复|作答|输出)/u.test(
      prompt,
    ) ||
    /\b(?:respond|reply|answer|write|output)\b[^.\n]{0,32}\b(?:in|using)\s+(?:the\s+)?english\b|\benglish\s+only\b/iu.test(
      prompt,
    );
  const chineseRequested =
    /(?:请|仅|只|必须|务必|用|使用|以)[^。\n]{0,12}(?:简体中文|中文)|(?:简体中文|中文)[^。\n]{0,8}(?:回答|回复|作答|输出)/u.test(
      prompt,
    ) ||
    /\b(?:respond|reply|answer|write|output)\b[^.\n]{0,32}\b(?:in|using)\s+(?:the\s+)?(?:simplified\s+)?chinese\b|\b(?:simplified\s+)?chinese\s+only\b/iu.test(
      prompt,
    );
  if (englishRequested === chineseRequested) return undefined;
  return chineseRequested ? 'zh-CN' : 'en';
}

export function resolveV3ResponseLanguage(
  latestUserPrompt: string,
  persistedPreference: V3SendMessage['responseLanguage'],
): V3SendMessage['responseLanguage'] {
  const explicitLanguage = explicitV3ResponseLanguage(latestUserPrompt);
  if (explicitLanguage) return explicitLanguage;
  const hanCharacters = latestUserPrompt.match(/\p{Script=Han}/gu)?.length ?? 0;
  const latinCharacters = latestUserPrompt.match(/[A-Za-z]/gu)?.length ?? 0;
  if (hanCharacters >= 4 && hanCharacters * 2 >= latinCharacters) return 'zh-CN';
  if (latinCharacters >= 8 && latinCharacters > hanCharacters * 2) return 'en';
  return persistedPreference;
}

export function withV3ResponseLanguage(
  systemPrompt: string,
  responseLanguage: V3SendMessage['responseLanguage'],
): string {
  if (!responseLanguage) return systemPrompt;
  const instruction =
    responseLanguage === 'zh-CN'
      ? 'Respond to the user in Simplified Chinese unless the user explicitly asks for another language.'
      : 'Respond to the user in English unless the user explicitly asks for another language.';
  return `${systemPrompt}\n\n## Default response language\n${instruction}`;
}

export function withV3ResponseLanguagePrompt(
  prompt: string,
  responseLanguage: V3SendMessage['responseLanguage'],
): string {
  if (!responseLanguage) return prompt;
  const language = responseLanguage === 'zh-CN' ? 'Simplified Chinese' : 'English';
  return `[Persisted response-language preference: reply in ${language} unless this message explicitly requests another language.]\n\n${prompt}`;
}
