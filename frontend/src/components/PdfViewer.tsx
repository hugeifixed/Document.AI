import type { ReactNode } from "react";
import { Document as PdfDocument, pdfjs, Page as PdfPage } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export function PdfViewer({
  file,
  pageNumber,
  scale,
  children,
}: {
  file: string;
  pageNumber: number;
  scale: number;
  children: ReactNode;
}) {
  return (
    <PdfDocument
      file={file}
      loading={<output className="block">Rendering…</output>}
      error={<p role="alert">The PDF could not be rendered.</p>}
    >
      <div className="relative">
        <PdfPage pageNumber={pageNumber} scale={scale} renderTextLayer renderAnnotationLayer={false} />
        <div className="pointer-events-none absolute inset-0">{children}</div>
      </div>
    </PdfDocument>
  );
}
