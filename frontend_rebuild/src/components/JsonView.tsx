interface JsonViewProps {
  data: unknown;
}

export function JsonView({ data }: JsonViewProps) {
  return (
    <pre className="json-view">
      {typeof data === "string" ? data : JSON.stringify(data, null, 2)}
    </pre>
  );
}

