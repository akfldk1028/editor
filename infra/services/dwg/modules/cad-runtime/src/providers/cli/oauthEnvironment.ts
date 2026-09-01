const disallowedCredentialNames = new Set([
  "OPENAI_API_KEY",
  "ANTHROPIC_API_KEY",
  "CLAUDE_API_KEY"
]);

export function createOAuthOnlyEnvironment(
  source: NodeJS.ProcessEnv = process.env
): NodeJS.ProcessEnv {
  return Object.fromEntries(
    Object.entries(source).filter(
      ([name, value]) =>
        value !== undefined && !disallowedCredentialNames.has(name.toUpperCase())
    )
  );
}
