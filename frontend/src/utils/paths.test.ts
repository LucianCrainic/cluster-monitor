import { describe, expect, it } from "vitest";

import { quotePosixPath } from "./paths";

describe("quotePosixPath", () => {
  it("keeps safe paths readable and quotes shell metacharacters", () => {
    expect(quotePosixPath("/home/user/job.sh")).toBe("/home/user/job.sh");
    expect(quotePosixPath("/home/user/a b;$(touch nope).sh")).toBe(
      "'/home/user/a b;$(touch nope).sh'",
    );
    expect(quotePosixPath("/home/user/it's.sh")).toBe(
      "'/home/user/it'\"'\"'s.sh'",
    );
  });
});
