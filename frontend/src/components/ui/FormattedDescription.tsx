import { Fragment } from "react";
import { cleanDescription } from "@/lib/utils/format";

const URL_RE = /(https?:\/\/[^\s<>()]+)/g;

function splitTrailingPunctuation(rawUrl: string): { url: string; trailing: string } {
  let url = rawUrl;
  let trailing = "";
  while (url.length > 0 && /[.,;:!?]$/.test(url)) {
    trailing = url.slice(-1) + trailing;
    url = url.slice(0, -1);
  }
  return { url, trailing };
}

/**
 * Renders a market description with accidental double periods cleaned up and
 * embedded http(s) URLs turned into safe external links.
 */
export function FormattedDescription({ text }: { text: string }) {
  const cleaned = cleanDescription(text);
  const parts = cleaned.split(URL_RE);

  return (
    <>
      {parts.map((part, idx) => {
        if (part.startsWith("http://") || part.startsWith("https://")) {
          const { url, trailing } = splitTrailingPunctuation(part);
          return (
            <Fragment key={idx}>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ overflowWrap: "anywhere", textDecoration: "underline" }}
              >
                {url}
              </a>
              {trailing}
            </Fragment>
          );
        }
        return <Fragment key={idx}>{part}</Fragment>;
      })}
    </>
  );
}
