import type { AnswerBlock, AnswerInline } from "./assistant-answer-model";
import { parseAssistantAnswer } from "./assistant-answer-model";
import styles from "./assistant.module.css";

function InlineText({ parts }: { parts: AnswerInline[] }) {
  return <>{parts.map((part, index) => {
    if (part.kind === "strong") return <strong key={index}>{part.text}</strong>;
    if (part.kind === "code") return <code key={index}>{part.text}</code>;
    return <span className={styles.answerInlineText} key={index}>{part.text}</span>;
  })}</>;
}

function Block({ block, index }: { block: AnswerBlock; index: number }) {
  if (block.kind === "heading") {
    const Heading = `h${block.level}` as "h2" | "h3" | "h4";
    return <Heading className={styles.answerHeading}><InlineText parts={block.content} /></Heading>;
  }
  if (block.kind === "paragraph") return <p><InlineText parts={block.content} /></p>;
  if (block.kind === "list") {
    const List = block.ordered ? "ol" : "ul";
    return <List>{block.items.map((item, itemIndex) => <li key={`${index}:${itemIndex}`}><InlineText parts={item} /></li>)}</List>;
  }
  if (block.kind === "key-values") {
    return <dl className={styles.answerKeyValues}>{block.rows.map((row, rowIndex) => <div key={`${index}:${rowIndex}`}><dt>{row.key}</dt><dd><InlineText parts={row.value} /></dd></div>)}</dl>;
  }
  if (block.kind === "overflow") {
    return <details className={styles.answerOverflow}><summary>Show remaining answer as plain text</summary><pre>{block.remaining}</pre>{block.truncated ? <p role="note">The remaining text exceeded the bounded display size. Reopen the saved answer to continue from its transcript.</p> : null}</details>;
  }
  return <div className={styles.answerTableWrap} role="region" aria-label="Assistant answer table" tabIndex={0}>
    <table className={styles.answerTable}><thead><tr>{block.headers.map((header, cellIndex) => <th scope="col" key={`${index}:head:${cellIndex}`}>{header}</th>)}</tr></thead>
      <tbody>{block.rows.map((row, rowIndex) => <tr key={`${index}:row:${rowIndex}`}>{block.headers.map((_, cellIndex) => <td key={`${index}:${rowIndex}:${cellIndex}`}>{row[cellIndex] ?? ""}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

/** React text nodes keep provider content inert; this renderer creates no raw HTML or links. */
export function AssistantAnswer({ text }: { text: string }) {
  return <div className={styles.answerBlocks}>{parseAssistantAnswer(text).map((block, index) => <Block block={block} index={index} key={index} />)}</div>;
}
