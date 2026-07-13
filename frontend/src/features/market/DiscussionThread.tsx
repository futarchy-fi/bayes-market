import { useState } from "react";
import { useSession } from "@/features/session/context";
import { useMarketComments, usePostMarketComment } from "@/lib/query/hooks";
import { formatRelativeTime } from "@/lib/utils/format";
import type { Market } from "@/lib/api/types";
import { isExchangeMode } from "@/lib/exchangeMode";
import { ExchangeUnavailable } from "@/components/ui/ExchangeUnavailable";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";

const MAX_COMMENT_BODY_LENGTH = 2000;

interface DiscussionThreadProps {
  market: Market;
}

export function DiscussionThread({ market }: DiscussionThreadProps) {
  const { session, isConfigured } = useSession();
  const comments = useMarketComments(market.id);
  const mutation = usePostMarketComment(market.id);
  const [body, setBody] = useState("");

  if (isExchangeMode()) return <ExchangeUnavailable title="Discussion" />;

  const trimmedBody = body.trim();
  const remaining = MAX_COMMENT_BODY_LENGTH - body.length;
  const isReadOnly = market.status !== "active";

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isConfigured || isReadOnly || !trimmedBody) {
      return;
    }

    mutation.mutate(
      {
        payload: {
          accountId: session.accountId,
          body: trimmedBody,
          idempotencyKey: crypto.randomUUID(),
        },
        session,
      },
      {
        onSuccess: () => {
          setBody("");
        },
      },
    );
  };

  return (
    <section style={panelStyle}>
      <div style={headerStyle}>
        <div>
          <h2 style={titleStyle}>Discussion</h2>
          <p style={subtitleStyle}>Market commentary and participant notes.</p>
        </div>
        {comments.data && (
          <span style={countStyle}>
            {comments.data.pagination.returned} comment{comments.data.pagination.returned === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <div style={threadStyle}>
        {comments.isLoading && <span style={mutedTextStyle}>Loading discussion...</span>}
        {comments.isError && comments.data && <ReconnectingHint />}
        {comments.isError && !comments.data && (
          <span style={errorTextStyle}>
            {comments.error instanceof Error ? comments.error.message : "Failed to load comments"}
          </span>
        )}
        {comments.data && comments.data.comments.length === 0 && (
          <span style={mutedTextStyle}>No comments yet.</span>
        )}
        {comments.data && comments.data.comments.length > 0 && (
          <div style={commentListStyle}>
            {comments.data.comments.map((comment) => (
              <article key={comment.commentId} style={commentCardStyle}>
                <div style={commentMetaRowStyle}>
                  <strong style={commentAuthorStyle}>{comment.accountId}</strong>
                  <span style={commentMetaStyle}>#{comment.seq}</span>
                  <span style={commentMetaStyle}>{formatRelativeTime(comment.createdAt)}</span>
                </div>
                <p style={commentBodyStyle}>{comment.body}</p>
              </article>
            ))}
          </div>
        )}
      </div>

      {isReadOnly ? (
        <div style={noteStyle}>Discussion is read-only because this market is {market.status}.</div>
      ) : !isConfigured ? (
        <div style={noteStyle}>Set your Account ID in the header to join the discussion.</div>
      ) : (
        <form onSubmit={handleSubmit} style={composerStyle}>
          <label style={{ display: "grid", gap: "var(--space-xs)" }}>
            <span style={labelStyle}>Add a comment</span>
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="Share your thesis, assumptions, or trade rationale."
              maxLength={MAX_COMMENT_BODY_LENGTH}
              rows={4}
              style={textareaStyle}
            />
          </label>
          <div style={composerFooterStyle}>
            <span style={mutedTextStyle}>{remaining} characters remaining</span>
            <button
              type="submit"
              disabled={!trimmedBody || mutation.isPending}
              style={{
                ...submitButtonStyle,
                opacity: !trimmedBody || mutation.isPending ? 0.6 : 1,
                cursor: !trimmedBody || mutation.isPending ? "not-allowed" : "pointer",
              }}
            >
              {mutation.isPending ? "Posting..." : "Post Comment"}
            </button>
          </div>
          {mutation.isError && (
            <div style={errorTextStyle}>
              {mutation.error instanceof Error ? mutation.error.message : "Failed to post comment"}
            </div>
          )}
        </form>
      )}
    </section>
  );
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  display: "grid",
  gap: "var(--space-md)",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-md)",
  flexWrap: "wrap",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "1.1rem",
  fontWeight: 600,
};

const subtitleStyle: React.CSSProperties = {
  margin: "4px 0 0 0",
  color: "var(--color-text-muted)",
  fontSize: "0.85rem",
};

const countStyle: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: "999px",
  border: "1px solid var(--color-border)",
  color: "var(--color-text-muted)",
  fontSize: "0.75rem",
  fontFamily: "var(--font-mono)",
};

const threadStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-sm)",
};

const commentListStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-sm)",
};

const commentCardStyle: React.CSSProperties = {
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  padding: "var(--space-sm) var(--space-md)",
  display: "grid",
  gap: "var(--space-xs)",
};

const commentMetaRowStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-sm)",
};

const commentAuthorStyle: React.CSSProperties = {
  fontSize: "0.85rem",
  fontWeight: 600,
};

const commentMetaStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.75rem",
};

const commentBodyStyle: React.CSSProperties = {
  margin: 0,
  whiteSpace: "pre-wrap",
  lineHeight: 1.5,
  fontSize: "0.9rem",
};

const composerStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-sm)",
  paddingTop: "var(--space-xs)",
  borderTop: "1px solid var(--color-border)",
};

const labelStyle: React.CSSProperties = {
  fontSize: "0.85rem",
  fontWeight: 600,
};

const textareaStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.9rem",
  fontFamily: "inherit",
  resize: "vertical",
};

const composerFooterStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: "var(--space-sm)",
  flexWrap: "wrap",
};

const submitButtonStyle: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: "var(--radius-sm)",
  border: "none",
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
  fontSize: "0.85rem",
};

const noteStyle: React.CSSProperties = {
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-sm)",
  border: "1px dashed var(--color-border)",
  color: "var(--color-text-muted)",
  background: "rgba(15, 23, 42, 0.02)",
  fontSize: "0.85rem",
};

const mutedTextStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.85rem",
};

const errorTextStyle: React.CSSProperties = {
  color: "var(--color-danger)",
  fontSize: "0.85rem",
};
