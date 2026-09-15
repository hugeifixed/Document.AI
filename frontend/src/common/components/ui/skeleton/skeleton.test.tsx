import { render } from "@testing-library/react";
import { Skeleton } from "./skeleton";
it("preserves accessible shared behavior", () => { const {container} = render(<Skeleton />); expect(container.firstChild).toHaveAttribute("aria-hidden", "true"); });
