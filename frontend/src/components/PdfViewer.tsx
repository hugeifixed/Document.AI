import { type ReactNode, useEffect, useState } from "react";
import { Document as PdfDocument, pdfjs, Page as PdfPage } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

type PageProps = {
  pageNumber: number;
  scale: number;
  children: ReactNode;
  renderTextLayer?: boolean;
  onPageRendered?: () => void;
};

// A new page/scale gets its own readiness state. An obsolete canvas callback cannot
// expose overlays or notify the parent after this surface has unmounted.
function PdfSurface({ pageNumber, scale, children, renderTextLayer, onPageRendered }: PageProps) {
  const [rendered, setRendered] = useState(false);
  useEffect(() => {
    if (rendered) onPageRendered?.();
  }, [rendered, onPageRendered]);
  return (
    <div className="relative w-max" data-pdf-page={pageNumber} data-rendered={rendered}>
      <PdfPage
        pageNumber={pageNumber}
        scale={scale}
        renderTextLayer={renderTextLayer}
        renderAnnotationLayer={false}
        onRenderSuccess={() => setRendered(true)}
      />
      {rendered && <div className="pointer-events-none absolute inset-0">{children}</div>}
    </div>
  );
}

export function PdfViewer({
  file,
  pageNumber,
  scale,
  children,
  renderTextLayer = true,
  onPageRendered,
}: PageProps & {
  file: string;
}) {
  return (
    <PdfDocument
      file={file}
      loading={<output className="block">Rendering…</output>}
      error={<p role="alert">The PDF could not be rendered.</p>}
    >
      <PdfSurface
        key={`${file}:${pageNumber}:${scale}`}
        pageNumber={pageNumber}
        scale={scale}
        renderTextLayer={renderTextLayer}
        onPageRendered={onPageRendered}
      >
        {children}
      </PdfSurface>
    </PdfDocument>
  );
}
